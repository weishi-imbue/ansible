# (C) 2013, James Cammarata <jcammarata@ansible.com>
# Copyright: (c) 2019, Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import hashlib
import json
import os
import stat
import tarfile
import threading
import time
import uuid
from collections import namedtuple
from functools import wraps

from ansible import constants as C
from ansible.errors import AnsibleError
from ansible.galaxy.user_agent import user_agent
from ansible.module_utils.six import string_types
from ansible.module_utils.six.moves.urllib.error import HTTPError
from ansible.module_utils.six.moves.urllib.parse import quote as urlquote, urlencode, urlparse
from ansible.module_utils._text import to_bytes, to_native, to_text
from ansible.module_utils.urls import open_url, prepare_multipart
from ansible.utils.display import Display
from ansible.utils.hashing import secure_hash_s

try:
    from urllib.parse import urlparse
except ImportError:
    # Python 2
    from urlparse import urlparse

display = Display()

# Cache lock for thread-safe cache access
_CACHE_LOCK = threading.Lock()

# Cache format version
CACHE_VERSION = 1

# Collection metadata named tuple
CollectionMetadata = namedtuple('CollectionMetadata', ['namespace', 'name', 'created', 'modified'])


def cache_lock(func):
    """
    Wrapper function that enforces serialized execution using a module-level lock
    to ensure thread-safe access to shared cache files.

    :param func: The function to wrap with locking
    :return: The wrapped function
    """
    @wraps(func)
    def wrapped(*args, **kwargs):
        with _CACHE_LOCK:
            return func(*args, **kwargs)
    return wrapped


def get_cache_id(server_url):
    """
    Generate a sanitized cache identifier from a Galaxy server URL.

    :param server_url: The Galaxy server URL
    :return: A cache identifier in the format 'hostname:port'
    """
    parsed = urlparse(server_url)
    # Use hostname and port only, explicitly omitting credentials
    hostname = parsed.hostname or 'unknown'
    port = parsed.port

    if port:
        return '%s:%s' % (hostname, port)
    else:
        # Use default ports for common schemes
        if parsed.scheme == 'https':
            return '%s:443' % hostname
        elif parsed.scheme == 'http':
            return '%s:80' % hostname
        else:
            return hostname


def g_connect(versions):
    """
    Wrapper to lazily initialize connection info to Galaxy and verify the API versions required are available on the
    endpoint.

    :param versions: A list of API versions that the function supports.
    """
    def decorator(method):
        def wrapped(self, *args, **kwargs):
            if not self._available_api_versions:
                display.vvvv("Initial connection to galaxy_server: %s" % self.api_server)

                # Determine the type of Galaxy server we are talking to. First try it unauthenticated then with Bearer
                # auth for Automation Hub.
                n_url = self.api_server
                error_context_msg = 'Error when finding available api versions from %s (%s)' % (self.name, n_url)

                if self.api_server == 'https://galaxy.ansible.com' or self.api_server == 'https://galaxy.ansible.com/':
                    n_url = 'https://galaxy.ansible.com/api/'

                try:
                    data = self._call_galaxy(n_url, method='GET', error_context_msg=error_context_msg)
                except (AnsibleError, GalaxyError, ValueError, KeyError) as err:
                    # Either the URL doesnt exist, or other error. Or the URL exists, but isn't a galaxy API
                    # root (not JSON, no 'available_versions') so try appending '/api/'
                    if n_url.endswith('/api') or n_url.endswith('/api/'):
                        raise

                    # Let exceptions here bubble up but raise the original if this returns a 404 (/api/ wasn't found).
                    n_url = _urljoin(n_url, '/api/')
                    try:
                        data = self._call_galaxy(n_url, method='GET', error_context_msg=error_context_msg)
                    except GalaxyError as new_err:
                        if new_err.http_code == 404:
                            raise err
                        raise

                if 'available_versions' not in data:
                    raise AnsibleError("Tried to find galaxy API root at %s but no 'available_versions' are available "
                                       "on %s" % (n_url, self.api_server))

                # Update api_server to point to the "real" API root, which in this case could have been the configured
                # url + '/api/' appended.
                self.api_server = n_url

                # Default to only supporting v1, if only v1 is returned we also assume that v2 is available even though
                # it isn't returned in the available_versions dict.
                available_versions = data.get('available_versions', {u'v1': u'v1/'})
                if list(available_versions.keys()) == [u'v1']:
                    available_versions[u'v2'] = u'v2/'

                self._available_api_versions = available_versions
                display.vvvv("Found API version '%s' with Galaxy server %s (%s)"
                             % (', '.join(available_versions.keys()), self.name, self.api_server))

            # Verify that the API versions the function works with are available on the server specified.
            available_versions = set(self._available_api_versions.keys())
            common_versions = set(versions).intersection(available_versions)
            if not common_versions:
                raise AnsibleError("Galaxy action %s requires API versions '%s' but only '%s' are available on %s %s"
                                   % (method.__name__, ", ".join(versions), ", ".join(available_versions),
                                      self.name, self.api_server))

            return method(self, *args, **kwargs)
        return wrapped
    return decorator


def _urljoin(*args):
    return '/'.join(to_native(a, errors='surrogate_or_strict').strip('/') for a in args + ('',) if a)


class GalaxyError(AnsibleError):
    """ Error for bad Galaxy server responses. """

    def __init__(self, http_error, message):
        super(GalaxyError, self).__init__(message)
        self.http_code = http_error.code
        self.url = http_error.geturl()

        try:
            http_msg = to_text(http_error.read())
            err_info = json.loads(http_msg)
        except (AttributeError, ValueError):
            err_info = {}

        url_split = self.url.split('/')
        if 'v2' in url_split:
            galaxy_msg = err_info.get('message', http_error.reason)
            code = err_info.get('code', 'Unknown')
            full_error_msg = u"%s (HTTP Code: %d, Message: %s Code: %s)" % (message, self.http_code, galaxy_msg, code)
        elif 'v3' in url_split:
            errors = err_info.get('errors', [])
            if not errors:
                errors = [{}]  # Defaults are set below, we just need to make sure 1 error is present.

            message_lines = []
            for error in errors:
                error_msg = error.get('detail') or error.get('title') or http_error.reason
                error_code = error.get('code') or 'Unknown'
                message_line = u"(HTTP Code: %d, Message: %s Code: %s)" % (self.http_code, error_msg, error_code)
                message_lines.append(message_line)

            full_error_msg = "%s %s" % (message, ', '.join(message_lines))
        else:
            # v1 and unknown API endpoints
            galaxy_msg = err_info.get('default', http_error.reason)
            full_error_msg = u"%s (HTTP Code: %d, Message: %s)" % (message, self.http_code, galaxy_msg)

        self.message = to_native(full_error_msg)


class CollectionVersionMetadata:

    def __init__(self, namespace, name, version, download_url, artifact_sha256, dependencies):
        """
        Contains common information about a collection on a Galaxy server to smooth through API differences for
        Collection and define a standard meta info for a collection.

        :param namespace: The namespace name.
        :param name: The collection name.
        :param version: The version that the metadata refers to.
        :param download_url: The URL to download the collection.
        :param artifact_sha256: The SHA256 of the collection artifact for later verification.
        :param dependencies: A dict of dependencies of the collection.
        """
        self.namespace = namespace
        self.name = name
        self.version = version
        self.download_url = download_url
        self.artifact_sha256 = artifact_sha256
        self.dependencies = dependencies


class GalaxyAPI:
    """ This class is meant to be used as a API client for an Ansible Galaxy server """

    def __init__(self, galaxy, name, url, username=None, password=None, token=None, validate_certs=True,
                 available_api_versions=None):
        self.galaxy = galaxy
        self.name = name
        self.username = username
        self.password = password
        self.token = token
        self.api_server = url
        self.validate_certs = validate_certs
        self._available_api_versions = available_api_versions or {}

        display.debug('Validate TLS certificates for %s: %s' % (self.api_server, self.validate_certs))

    @property
    @g_connect(['v1', 'v2', 'v3'])
    def available_api_versions(self):
        # Calling g_connect will populate self._available_api_versions
        return self._available_api_versions

    def _get_cache_path(self):
        """Get the cache directory path for this Galaxy server."""
        cache_dir = os.path.expanduser(C.GALAXY_CACHE_DIR)
        server_id = get_cache_id(self.api_server)
        return os.path.join(cache_dir, server_id)

    def _get_cache_file_path(self):
        """Get the cache file path for this Galaxy server."""
        return os.path.join(self._get_cache_path(), 'api.json')

    @cache_lock
    def _load_cache(self):
        """Load cached responses from disk."""
        cache_file = self._get_cache_file_path()

        if not os.path.exists(cache_file):
            return {}

        try:
            # Check file permissions - reject world-writable files
            file_stat = os.stat(cache_file)
            if file_stat.st_mode & stat.S_IWOTH:
                display.warning("Ignoring world-writable cache file %s for security reasons" % cache_file)
                return {}

            with open(cache_file, 'r') as f:
                cache_data = json.load(f)

            # Validate cache version
            cache_version = cache_data.get('version', 0)
            if cache_version != CACHE_VERSION:
                display.vvv("Cache version mismatch (expected %s, got %s), ignoring cache" % (CACHE_VERSION, cache_version))
                return {}

            return cache_data.get('data', {})
        except (IOError, OSError, ValueError) as e:
            display.vvv("Failed to load cache from %s: %s" % (cache_file, to_native(e)))
            return {}

    @cache_lock
    def _save_cache(self, cache_data):
        """Save cached responses to disk."""
        cache_file = self._get_cache_file_path()
        cache_dir = self._get_cache_path()
        temp_file = None

        try:
            # Create cache directory if it doesn't exist
            if not os.path.exists(cache_dir):
                os.makedirs(cache_dir, 0o700)

            # Prepare cache file data with version marker
            file_data = {
                'version': CACHE_VERSION,
                'data': cache_data
            }

            # Write to temporary file first, then rename for atomicity
            temp_file = cache_file + '.tmp'
            with open(temp_file, 'w') as f:
                json.dump(file_data, f, separators=(',', ':'))

            # Set proper permissions before moving
            os.chmod(temp_file, 0o600)

            # Atomic rename
            os.rename(temp_file, cache_file)

        except (IOError, OSError) as e:
            display.vvv("Failed to save cache to %s: %s" % (cache_file, to_native(e)))
            # Clean up temp file if it exists
            if temp_file is not None:
                try:
                    os.unlink(temp_file)
                except (IOError, OSError):
                    pass

    def _should_use_cache(self, url, args):
        """Determine if we should use cache for this request."""
        from ansible import context

        # Don't cache if --no-cache flag is set
        if context.CLIARGS.get('no_cache', False):
            return False

        # Don't cache requests with query parameters (they're likely dynamic)
        parsed_url = urlparse(url)
        if parsed_url.query or args:
            return False

        return True

    def _get_cache_key(self, url, method='GET'):
        """Generate cache key for a request."""
        # Use URL path only (without query parameters) and method
        parsed_url = urlparse(url)
        cache_key = '%s_%s' % (method.upper(), parsed_url.path)
        return cache_key.replace('/', '_').replace(':', '_')

    def _is_cache_valid(self, cache_entry, url):
        """Check if a cache entry is still valid."""
        # For collection version listings, check if collection metadata has changed
        parsed_url = urlparse(url)
        path_parts = parsed_url.path.strip('/').split('/')

        # Check if this is a collection versions request
        if ('collections' in path_parts and 'versions' in path_parts and
            len(path_parts) >= 4):
            try:
                # Extract namespace and name from URL path
                collections_idx = path_parts.index('collections')
                if collections_idx + 2 < len(path_parts):
                    namespace = path_parts[collections_idx + 1]
                    name = path_parts[collections_idx + 2]

                    # Get current collection metadata, bypassing cache to avoid circular dependency
                    current_metadata = self.get_collection_metadata(namespace, name, use_cache=False)

                    # Compare with cached metadata if available
                    cached_modified = cache_entry.get('collection_modified')
                    if cached_modified and current_metadata.modified:
                        if current_metadata.modified != cached_modified:
                            display.vvv("Collection %s.%s modified time changed, invalidating cache" % (namespace, name))
                            return False

            except (ValueError, IndexError, Exception) as e:
                # If we can't determine collection info, assume cache is valid
                display.vvv("Could not check collection metadata for cache validation: %s" % to_native(e))

        return True

    @cache_lock
    def _invalidate_collection_cache(self, namespace, name):
        """Invalidate cached responses for a specific collection."""
        cache_data = self._load_cache()
        keys_to_remove = []

        for cache_key in cache_data:
            cache_entry = cache_data[cache_key]
            url = cache_entry.get('url', '')
            parsed_url = urlparse(url)
            path_parts = parsed_url.path.strip('/').split('/')

            # Check if this cache entry is for the specified collection
            if ('collections' in path_parts and len(path_parts) >= 4):
                try:
                    collections_idx = path_parts.index('collections')
                    if (collections_idx + 2 < len(path_parts) and
                        path_parts[collections_idx + 1] == namespace and
                        path_parts[collections_idx + 2] == name):
                        keys_to_remove.append(cache_key)
                except (ValueError, IndexError):
                    continue

        # Remove invalidated entries
        for key in keys_to_remove:
            del cache_data[key]

        if keys_to_remove:
            self._save_cache(cache_data)
            display.vvv("Invalidated %d cache entries for collection %s.%s" % (len(keys_to_remove), namespace, name))

    def _call_galaxy(self, url, args=None, headers=None, method=None, auth_required=False, error_context_msg=None, use_cache=None):
        headers = headers or {}
        method = method or 'GET'
        self._add_auth_token(headers, url, required=auth_required)

        # Check if we should use cache for this request
        # use_cache parameter can override the default behavior
        if use_cache is None:
            use_cache = self._should_use_cache(url, args)
        cache_key = None

        if use_cache:
            cache_key = self._get_cache_key(url, method)
            cache_data = self._load_cache()

            # Check if we have a cached response
            if cache_key in cache_data:
                cache_entry = cache_data[cache_key]
                if self._is_cache_valid(cache_entry, url):
                    display.vvv("Using cached response for %s" % url)
                    return cache_entry['response']

        try:
            display.vvvv("Calling Galaxy at %s" % url)
            resp = open_url(to_native(url), data=args, validate_certs=self.validate_certs, headers=headers,
                            method=method, timeout=20, http_agent=user_agent(), follow_redirects='safe')
        except HTTPError as e:
            raise GalaxyError(e, error_context_msg)
        except Exception as e:
            raise AnsibleError("Unknown error when attempting to call Galaxy at '%s': %s" % (url, to_native(e)))

        resp_data = to_text(resp.read(), errors='surrogate_or_strict')
        try:
            data = json.loads(resp_data)
        except ValueError:
            raise AnsibleError("Failed to parse Galaxy response from '%s' as JSON:\n%s"
                               % (resp.url, to_native(resp_data)))

        # Cache the response if appropriate
        if use_cache and method.upper() == 'GET':
            cache_data = self._load_cache()
            cache_entry = {
                'response': data,
                'timestamp': time.time(),
                'url': url
            }

            # For collection-related URLs, store collection metadata for cache invalidation
            parsed_url = urlparse(url)
            path_parts = parsed_url.path.strip('/').split('/')
            if ('collections' in path_parts and len(path_parts) >= 4):
                try:
                    collections_idx = path_parts.index('collections')
                    if collections_idx + 2 < len(path_parts):
                        namespace = path_parts[collections_idx + 1]
                        name = path_parts[collections_idx + 2]

                        # Get collection metadata for cache invalidation
                        try:
                            metadata = self.get_collection_metadata(namespace, name)
                            if metadata.modified:
                                cache_entry['collection_modified'] = metadata.modified
                        except Exception as e:
                            # Don't fail caching if metadata retrieval fails
                            display.vvv("Failed to get collection metadata for caching: %s" % to_native(e))
                except (ValueError, IndexError):
                    pass

            cache_data[cache_key] = cache_entry
            self._save_cache(cache_data)

        return data

    def _add_auth_token(self, headers, url, token_type=None, required=False):
        # Don't add the auth token if one is already present
        if 'Authorization' in headers:
            return

        if not self.token and required:
            raise AnsibleError("No access token or username set. A token can be set with --api-key "
                               "or at {0}.".format(to_native(C.GALAXY_TOKEN_PATH)))

        if self.token:
            headers.update(self.token.headers())

    @g_connect(['v1'])
    def authenticate(self, github_token):
        """
        Retrieve an authentication token
        """
        url = _urljoin(self.api_server, self.available_api_versions['v1'], "tokens") + '/'
        args = urlencode({"github_token": github_token})
        resp = open_url(url, data=args, validate_certs=self.validate_certs, method="POST", http_agent=user_agent())
        data = json.loads(to_text(resp.read(), errors='surrogate_or_strict'))
        return data

    @g_connect(['v1'])
    def create_import_task(self, github_user, github_repo, reference=None, role_name=None):
        """
        Post an import request
        """
        url = _urljoin(self.api_server, self.available_api_versions['v1'], "imports") + '/'
        args = {
            "github_user": github_user,
            "github_repo": github_repo,
            "github_reference": reference if reference else ""
        }
        if role_name:
            args['alternate_role_name'] = role_name
        elif github_repo.startswith('ansible-role'):
            args['alternate_role_name'] = github_repo[len('ansible-role') + 1:]
        data = self._call_galaxy(url, args=urlencode(args), method="POST")
        if data.get('results', None):
            return data['results']
        return data

    @g_connect(['v1'])
    def get_import_task(self, task_id=None, github_user=None, github_repo=None):
        """
        Check the status of an import task.
        """
        url = _urljoin(self.api_server, self.available_api_versions['v1'], "imports")
        if task_id is not None:
            url = "%s?id=%d" % (url, task_id)
        elif github_user is not None and github_repo is not None:
            url = "%s?github_user=%s&github_repo=%s" % (url, github_user, github_repo)
        else:
            raise AnsibleError("Expected task_id or github_user and github_repo")

        data = self._call_galaxy(url)
        return data['results']

    @g_connect(['v1'])
    def lookup_role_by_name(self, role_name, notify=True):
        """
        Find a role by name.
        """
        role_name = to_text(urlquote(to_bytes(role_name)))

        try:
            parts = role_name.split(".")
            user_name = ".".join(parts[0:-1])
            role_name = parts[-1]
            if notify:
                display.display("- downloading role '%s', owned by %s" % (role_name, user_name))
        except Exception:
            raise AnsibleError("Invalid role name (%s). Specify role as format: username.rolename" % role_name)

        url = _urljoin(self.api_server, self.available_api_versions['v1'], "roles",
                       "?owner__username=%s&name=%s" % (user_name, role_name))
        data = self._call_galaxy(url)
        if len(data["results"]) != 0:
            return data["results"][0]
        return None

    @g_connect(['v1'])
    def fetch_role_related(self, related, role_id):
        """
        Fetch the list of related items for the given role.
        The url comes from the 'related' field of the role.
        """

        results = []
        try:
            url = _urljoin(self.api_server, self.available_api_versions['v1'], "roles", role_id, related,
                           "?page_size=50")
            data = self._call_galaxy(url)
            results = data['results']
            done = (data.get('next_link', None) is None)

            # https://github.com/ansible/ansible/issues/64355
            # api_server contains part of the API path but next_link includes the /api part so strip it out.
            url_info = urlparse(self.api_server)
            base_url = "%s://%s/" % (url_info.scheme, url_info.netloc)

            while not done:
                url = _urljoin(base_url, data['next_link'])
                data = self._call_galaxy(url)
                results += data['results']
                done = (data.get('next_link', None) is None)
        except Exception as e:
            display.warning("Unable to retrieve role (id=%s) data (%s), but this is not fatal so we continue: %s"
                            % (role_id, related, to_text(e)))
        return results

    @g_connect(['v1'])
    def get_list(self, what):
        """
        Fetch the list of items specified.
        """
        try:
            url = _urljoin(self.api_server, self.available_api_versions['v1'], what, "?page_size")
            data = self._call_galaxy(url)
            if "results" in data:
                results = data['results']
            else:
                results = data
            done = True
            if "next" in data:
                done = (data.get('next_link', None) is None)
            while not done:
                url = _urljoin(self.api_server, data['next_link'])
                data = self._call_galaxy(url)
                results += data['results']
                done = (data.get('next_link', None) is None)
            return results
        except Exception as error:
            raise AnsibleError("Failed to download the %s list: %s" % (what, to_native(error)))

    @g_connect(['v1'])
    def search_roles(self, search, **kwargs):

        search_url = _urljoin(self.api_server, self.available_api_versions['v1'], "search", "roles", "?")

        if search:
            search_url += '&autocomplete=' + to_text(urlquote(to_bytes(search)))

        tags = kwargs.get('tags', None)
        platforms = kwargs.get('platforms', None)
        page_size = kwargs.get('page_size', None)
        author = kwargs.get('author', None)

        if tags and isinstance(tags, string_types):
            tags = tags.split(',')
            search_url += '&tags_autocomplete=' + '+'.join(tags)

        if platforms and isinstance(platforms, string_types):
            platforms = platforms.split(',')
            search_url += '&platforms_autocomplete=' + '+'.join(platforms)

        if page_size:
            search_url += '&page_size=%s' % page_size

        if author:
            search_url += '&username_autocomplete=%s' % author

        data = self._call_galaxy(search_url)
        return data

    @g_connect(['v1'])
    def add_secret(self, source, github_user, github_repo, secret):
        url = _urljoin(self.api_server, self.available_api_versions['v1'], "notification_secrets") + '/'
        args = urlencode({
            "source": source,
            "github_user": github_user,
            "github_repo": github_repo,
            "secret": secret
        })
        data = self._call_galaxy(url, args=args, method="POST")
        return data

    @g_connect(['v1'])
    def list_secrets(self):
        url = _urljoin(self.api_server, self.available_api_versions['v1'], "notification_secrets")
        data = self._call_galaxy(url, auth_required=True)
        return data

    @g_connect(['v1'])
    def remove_secret(self, secret_id):
        url = _urljoin(self.api_server, self.available_api_versions['v1'], "notification_secrets", secret_id) + '/'
        data = self._call_galaxy(url, auth_required=True, method='DELETE')
        return data

    @g_connect(['v1'])
    def delete_role(self, github_user, github_repo):
        url = _urljoin(self.api_server, self.available_api_versions['v1'], "removerole",
                       "?github_user=%s&github_repo=%s" % (github_user, github_repo))
        data = self._call_galaxy(url, auth_required=True, method='DELETE')
        return data

    # Collection APIs #

    @g_connect(['v2', 'v3'])
    def publish_collection(self, collection_path):
        """
        Publishes a collection to a Galaxy server and returns the import task URI.

        :param collection_path: The path to the collection tarball to publish.
        :return: The import task URI that contains the import results.
        """
        display.display("Publishing collection artifact '%s' to %s %s" % (collection_path, self.name, self.api_server))

        b_collection_path = to_bytes(collection_path, errors='surrogate_or_strict')
        if not os.path.exists(b_collection_path):
            raise AnsibleError("The collection path specified '%s' does not exist." % to_native(collection_path))
        elif not tarfile.is_tarfile(b_collection_path):
            raise AnsibleError("The collection path specified '%s' is not a tarball, use 'ansible-galaxy collection "
                               "build' to create a proper release artifact." % to_native(collection_path))

        with open(b_collection_path, 'rb') as collection_tar:
            sha256 = secure_hash_s(collection_tar.read(), hash_func=hashlib.sha256)

        content_type, b_form_data = prepare_multipart(
            {
                'sha256': sha256,
                'file': {
                    'filename': b_collection_path,
                    'mime_type': 'application/octet-stream',
                },
            }
        )

        headers = {
            'Content-type': content_type,
            'Content-length': len(b_form_data),
        }

        if 'v3' in self.available_api_versions:
            n_url = _urljoin(self.api_server, self.available_api_versions['v3'], 'artifacts', 'collections') + '/'
        else:
            n_url = _urljoin(self.api_server, self.available_api_versions['v2'], 'collections') + '/'

        resp = self._call_galaxy(n_url, args=b_form_data, headers=headers, method='POST', auth_required=True,
                                 error_context_msg='Error when publishing collection to %s (%s)'
                                                   % (self.name, self.api_server))

        return resp['task']

    @g_connect(['v2', 'v3'])
    def wait_import_task(self, task_id, timeout=0):
        """
        Waits until the import process on the Galaxy server has completed or the timeout is reached.

        :param task_id: The id of the import task to wait for. This can be parsed out of the return
            value for GalaxyAPI.publish_collection.
        :param timeout: The timeout in seconds, 0 is no timeout.
        """
        state = 'waiting'
        data = None

        # Construct the appropriate URL per version
        if 'v3' in self.available_api_versions:
            full_url = _urljoin(self.api_server, self.available_api_versions['v3'],
                                'imports/collections', task_id, '/')
        else:
            full_url = _urljoin(self.api_server, self.available_api_versions['v2'],
                                'collection-imports', task_id, '/')

        display.display("Waiting until Galaxy import task %s has completed" % full_url)
        start = time.time()
        wait = 2

        while timeout == 0 or (time.time() - start) < timeout:
            try:
                data = self._call_galaxy(full_url, method='GET', auth_required=True,
                                         error_context_msg='Error when getting import task results at %s' % full_url)
            except GalaxyError as e:
                if e.http_code != 404:
                    raise
                # The import job may not have started, and as such, the task url may not yet exist
                display.vvv('Galaxy import process has not started, wait %s seconds before trying again' % wait)
                time.sleep(wait)
                continue

            state = data.get('state', 'waiting')

            if data.get('finished_at', None):
                break

            display.vvv('Galaxy import process has a status of %s, wait %d seconds before trying again'
                        % (state, wait))
            time.sleep(wait)

            # poor man's exponential backoff algo so we don't flood the Galaxy API, cap at 30 seconds.
            wait = min(30, wait * 1.5)
        if state == 'waiting':
            raise AnsibleError("Timeout while waiting for the Galaxy import process to finish, check progress at '%s'"
                               % to_native(full_url))

        for message in data.get('messages', []):
            level = message['level']
            if level == 'error':
                display.error("Galaxy import error message: %s" % message['message'])
            elif level == 'warning':
                display.warning("Galaxy import warning message: %s" % message['message'])
            else:
                display.vvv("Galaxy import message: %s - %s" % (level, message['message']))

        if state == 'failed':
            code = to_native(data['error'].get('code', 'UNKNOWN'))
            description = to_native(
                data['error'].get('description', "Unknown error, see %s for more details" % full_url))
            raise AnsibleError("Galaxy import process failed: %s (Code: %s)" % (description, code))

    @g_connect(['v2', 'v3'])
    def get_collection_version_metadata(self, namespace, name, version):
        """
        Gets the collection information from the Galaxy server about a specific Collection version.

        :param namespace: The collection namespace.
        :param name: The collection name.
        :param version: Version of the collection to get the information for.
        :return: CollectionVersionMetadata about the collection at the version requested.
        """
        api_path = self.available_api_versions.get('v3', self.available_api_versions.get('v2'))
        url_paths = [self.api_server, api_path, 'collections', namespace, name, 'versions', version, '/']

        n_collection_url = _urljoin(*url_paths)
        error_context_msg = 'Error when getting collection version metadata for %s.%s:%s from %s (%s)' \
                            % (namespace, name, version, self.name, self.api_server)
        data = self._call_galaxy(n_collection_url, error_context_msg=error_context_msg)

        return CollectionVersionMetadata(data['namespace']['name'], data['collection']['name'], data['version'],
                                         data['download_url'], data['artifact']['sha256'],
                                         data['metadata']['dependencies'])

    @g_connect(['v2', 'v3'])
    def get_collection_versions(self, namespace, name):
        """
        Gets a list of available versions for a collection on a Galaxy server.

        :param namespace: The collection namespace.
        :param name: The collection name.
        :return: A list of versions that are available.
        """
        relative_link = False
        if 'v3' in self.available_api_versions:
            api_path = self.available_api_versions['v3']
            pagination_path = ['links', 'next']
            relative_link = True  # AH pagination results are relative an not an absolute URI.
        else:
            api_path = self.available_api_versions['v2']
            pagination_path = ['next']

        n_url = _urljoin(self.api_server, api_path, 'collections', namespace, name, 'versions', '/')

        error_context_msg = 'Error when getting available collection versions for %s.%s from %s (%s)' \
                            % (namespace, name, self.name, self.api_server)
        data = self._call_galaxy(n_url, error_context_msg=error_context_msg)

        if 'data' in data:
            # v3 automation-hub is the only known API that uses `data`
            # since v3 pulp_ansible does not, we cannot rely on version
            # to indicate which key to use
            results_key = 'data'
        else:
            results_key = 'results'

        versions = []
        while True:
            versions += [v['version'] for v in data[results_key]]

            next_link = data
            for path in pagination_path:
                next_link = next_link.get(path, {})

            if not next_link:
                break
            elif relative_link:
                # TODO: This assumes the pagination result is relative to the root server. Will need to be verified
                # with someone who knows the AH API.
                next_link = n_url.replace(urlparse(n_url).path, next_link)

            data = self._call_galaxy(to_native(next_link, errors='surrogate_or_strict'),
                                     error_context_msg=error_context_msg)

        return versions

    @g_connect(['v2', 'v3'])
    def get_collection_metadata(self, namespace, name, use_cache=None):
        """
        Gets collection metadata including created and modified fields for cache invalidation.

        :param namespace: The collection namespace.
        :param name: The collection name.
        :param use_cache: Whether to use cache for this request (None = auto, True = force use, False = bypass).
        :return: CollectionMetadata named tuple containing namespace, name, created, and modified timestamps.
        """
        if 'v3' in self.available_api_versions:
            # For v3 API (Automation Hub)
            api_path = self.available_api_versions['v3']
            n_url = _urljoin(self.api_server, api_path, 'collections', namespace, name, '/')
        else:
            # For v2 API (Galaxy)
            api_path = self.available_api_versions['v2']
            n_url = _urljoin(self.api_server, api_path, 'collections', namespace, name, '/')

        error_context_msg = 'Error when getting collection metadata for %s.%s from %s (%s)' \
                            % (namespace, name, self.name, self.api_server)
        data = self._call_galaxy(n_url, error_context_msg=error_context_msg, use_cache=use_cache)

        # Handle field mappings for different API versions
        if 'v3' in self.available_api_versions:
            # v3 API response structure
            created = data.get('created_at') or data.get('created')
            modified = data.get('updated_at') or data.get('modified')
        else:
            # v2 API response structure
            created = data.get('created') or data.get('created_at')
            modified = data.get('modified') or data.get('updated_at')

        return CollectionMetadata(
            namespace=namespace,
            name=name,
            created=created,
            modified=modified
        )
