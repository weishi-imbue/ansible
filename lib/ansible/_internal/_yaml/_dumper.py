from __future__ import annotations

import abc
import collections.abc as c
import typing as t

from yaml.representer import SafeRepresenter

from ansible.module_utils._internal._datatag import AnsibleTaggedObject, Tripwire, AnsibleTagHelper
from ansible.parsing.vault import VaultHelper
from ansible.module_utils.common.yaml import HAS_LIBYAML
from ansible.errors import AnsibleTemplateError
from ansible._internal._templating._jinja_common import VaultExceptionMarker

if HAS_LIBYAML:
    from yaml.cyaml import CSafeDumper as SafeDumper
else:
    from yaml import SafeDumper  # type: ignore[assignment]


class _BaseDumper(SafeDumper, metaclass=abc.ABCMeta):
    """Base class for Ansible YAML dumpers."""

    @classmethod
    @abc.abstractmethod
    def _register_representers(cls) -> None:
        """Method used to register representers to derived types during class initialization."""

    def __init_subclass__(cls, **kwargs) -> None:
        """Initialization for derived types."""
        cls._register_representers()


class AnsibleDumper(_BaseDumper):
    """A simple stub class that allows us to add representers for our custom types."""

    # DTFIX0: need a better way to handle serialization controls during YAML dumping
    def __init__(self, *args, dump_vault_tags: bool | None = None, **kwargs):
        super().__init__(*args, **kwargs)

        self._dump_vault_tags = dump_vault_tags

    @classmethod
    def _register_representers(cls) -> None:
        cls.add_multi_representer(AnsibleTaggedObject, cls.represent_ansible_tagged_object)
        cls.add_multi_representer(Tripwire, cls.represent_tripwire)
        cls.add_multi_representer(VaultExceptionMarker, cls.represent_vault_exception_marker)
        cls.add_multi_representer(c.Mapping, SafeRepresenter.represent_dict)
        cls.add_multi_representer(c.Sequence, SafeRepresenter.represent_list)

    def represent_ansible_tagged_object(self, data):
        if self._dump_vault_tags is not False and (ciphertext := VaultHelper.get_ciphertext(data, with_tags=False)):
            # deprecated: description='enable the deprecation warning below' core_version='2.23'
            # if self._dump_vault_tags is None:
            #     Display().deprecated(
            #         msg="Implicit YAML dumping of vaulted value ciphertext is deprecated. Set `dump_vault_tags` to explicitly specify the desired behavior",
            #         version="2.27",
            #     )

            return self.represent_scalar('!vault', ciphertext, style='|')

        # For dump_vault_tags=False, try to decrypt and only raise error if undecryptable
        if self._dump_vault_tags is False and VaultHelper.get_ciphertext(data, with_tags=False):
            try:
                decrypted = AnsibleTagHelper.as_native_type(data)
                return self.represent_data(decrypted)
            except Exception as e:
                # Failed to decrypt - this is an undecryptable vault value
                raise AnsibleTemplateError("Cannot serialize undecryptable vault value to YAML when dump_vault_tags=False") from e

        return self.represent_data(AnsibleTagHelper.as_native_type(data))  # automatically decrypts encrypted strings

    def represent_vault_exception_marker(self, data: VaultExceptionMarker):
        if self._dump_vault_tags is not False:
            # With dump_vault_tags enabled, serialize the undecryptable ciphertext as !vault
            ciphertext = data._marker_undecryptable_ciphertext
            return self.represent_scalar('!vault', ciphertext, style='|')
        else:
            # With dump_vault_tags=False, raise error for undecryptable vault values
            raise AnsibleTemplateError("Cannot serialize undecryptable vault value to YAML when dump_vault_tags=False")

    def represent_tripwire(self, data: Tripwire) -> t.NoReturn:
        data.trip()
