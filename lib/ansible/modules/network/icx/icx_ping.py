#!/usr/bin/python
# Copyright: Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type


ANSIBLE_METADATA = {'metadata_version': '1.1',
                    'status': ['preview'],
                    'supported_by': 'community'}


DOCUMENTATION = """
---
module: icx_ping
version_added: "2.9"
author: "Ruckus Wireless (@Commscope)"
short_description: Run ping commands for reachability testing on Ruckus ICX switches
description:
  - Execute ping commands directly on Ruckus ICX switches for automated network validation.
    This module allows network operators to perform device-side ICMP reachability tests
    and parse the results into structured data for automated decision-making.
notes:
  - Tested against ICX 10.1
options:
  dest:
    description:
      - The destination IP address or hostname to ping
    type: str
    required: true
  count:
    description:
      - Number of ping packets to send
    type: int
    default: 5
  timeout:
    description:
      - Timeout value in milliseconds (1-4294967294)
    type: int
    default: 2000
  ttl:
    description:
      - Time-to-live value for the ping packets (1-255)
    type: int
  size:
    description:
      - ICMP payload size in bytes (0-10000)
    type: int
  source:
    description:
      - Source IP address or interface for the ping
    type: str
  vrf:
    description:
      - VRF name for VRF-specific reachability testing
    type: str
  state:
    description:
      - Expected state of the ping result. When 'present', expects successful ping.
        When 'absent', expects ping to fail.
    type: str
    default: present
    choices: ['present', 'absent']
"""

EXAMPLES = """
- name: Basic ping test
  icx_ping:
    dest: 8.8.8.8

- name: Ping with specific parameters
  icx_ping:
    dest: 192.168.1.1
    count: 3
    timeout: 5000
    ttl: 64
    size: 1000

- name: Ping from specific source interface
  icx_ping:
    dest: 10.0.0.1
    source: 192.168.1.10
    count: 2

- name: VRF-specific ping test
  icx_ping:
    dest: 172.16.1.1
    vrf: management
    count: 3

- name: Expect ping to fail (negative test)
  icx_ping:
    dest: 192.168.255.255
    state: absent
    count: 2
"""

RETURN = """
packets_tx:
  description: Number of packets transmitted
  returned: always
  type: int
  sample: 5
packets_rx:
  description: Number of packets received
  returned: always
  type: int
  sample: 5
packet_loss:
  description: Packet loss percentage
  returned: always
  type: str
  sample: "0%"
rtt:
  description: Round trip time statistics
  returned: always
  type: dict
  contains:
    min:
      description: Minimum RTT in milliseconds
      type: int
      sample: 1
    avg:
      description: Average RTT in milliseconds
      type: int
      sample: 2
    max:
      description: Maximum RTT in milliseconds
      type: int
      sample: 3
"""

import re
from ansible.module_utils.network.icx.icx import run_commands
from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.connection import ConnectionError


def build_ping(dest, count=None, timeout=None, ttl=None, size=None, source=None, vrf=None):
    """
    Build ping command string with parameters in the correct order.

    Args:
        dest (str): destination IP or hostname
        count (int, optional): number of pings to send
        timeout (int, optional): timeout in milliseconds
        ttl (int, optional): time-to-live value
        size (int, optional): ICMP payload size in bytes
        source (str, optional): source IP address or interface
        vrf (str, optional): VRF name

    Returns:
        str: assembled ping command string
    """
    cmd_parts = ['ping']

    # Add parameters in order: vrf, dest, count, timeout, ttl, size, source
    if vrf is not None:
        cmd_parts.extend(['vrf', vrf])

    cmd_parts.append(dest)

    if count is not None:
        cmd_parts.extend(['count', str(count)])

    if timeout is not None:
        cmd_parts.extend(['timeout', str(timeout)])

    if ttl is not None:
        cmd_parts.extend(['ttl', str(ttl)])

    if size is not None:
        cmd_parts.extend(['size', str(size)])

    if source is not None:
        cmd_parts.extend(['source', source])

    return ' '.join(cmd_parts)


def parse_ping(ping_stats):
    """
    Parse ping output line containing ping summary.

    Args:
        ping_stats (str): raw output line containing ping summary

    Returns:
        tuple: (success_percent, rx, tx, rtt_dict)
            - success_percent (str): numeric string (e.g. "100")
            - rx (str): packets received
            - tx (str): packets transmitted
            - rtt (dict): round-trip time stats with keys "min", "avg", "max"
    """
    # Default return values
    success_percent = "0"
    rx = "0"
    tx = "0"
    rtt = {"min": 0, "avg": 0, "max": 0}

    # Check if line starts with "Success" - this indicates successful parsing
    if ping_stats.strip().startswith('Success'):
        # Parse success line format: "Success rate is 100 percent (5/5), round-trip min/avg/max = 1/2/3 ms"
        success_match = re.search(r'Success rate is (\d+) percent \((\d+)/(\d+)\)', ping_stats)
        if success_match:
            success_percent = success_match.group(1)
            rx = success_match.group(2)
            tx = success_match.group(3)

        # Parse RTT values
        rtt_match = re.search(r'round-trip min/avg/max = (\d+)/(\d+)/(\d+)', ping_stats)
        if rtt_match:
            rtt = {
                "min": int(rtt_match.group(1)),
                "avg": int(rtt_match.group(2)),
                "max": int(rtt_match.group(3))
            }
    else:
        # Fall back to "Sending" line format if no "Success" line found
        sending_match = re.search(r'Sending (\d+)', ping_stats)
        if sending_match:
            tx = sending_match.group(1)
        # rx remains 0, success_percent remains "0", rtt remains all zeros

    return success_percent, rx, tx, rtt


def main():
    """Main entry point for module execution"""
    argument_spec = dict(
        dest=dict(type='str', required=True),
        count=dict(type='int', default=5),
        timeout=dict(type='int', default=2000),
        ttl=dict(type='int'),
        size=dict(type='int'),
        source=dict(type='str'),
        vrf=dict(type='str'),
        state=dict(type='str', default='present', choices=['present', 'absent'])
    )

    module = AnsibleModule(argument_spec=argument_spec,
                           supports_check_mode=True)

    # Parameter validation
    params = module.params

    # Validate timeout range (1-4294967294)
    if params['timeout'] is not None and (params['timeout'] < 1 or params['timeout'] > 4294967294):
        module.fail_json(msg='timeout must be between 1 and 4294967294, got {0}'.format(params['timeout']))

    # Validate count range (1-4294967294)
    if params['count'] is not None and (params['count'] < 1 or params['count'] > 4294967294):
        module.fail_json(msg='count must be between 1 and 4294967294, got {0}'.format(params['count']))

    # Validate ttl range (1-255)
    if params['ttl'] is not None and (params['ttl'] < 1 or params['ttl'] > 255):
        module.fail_json(msg='ttl must be between 1 and 255, got {0}'.format(params['ttl']))

    # Validate size range (0-10000)
    if params['size'] is not None and (params['size'] < 0 or params['size'] > 10000):
        module.fail_json(msg='size must be between 0 and 10000, got {0}'.format(params['size']))

    result = {'changed': False}

    # Build ping command
    ping_cmd = build_ping(
        dest=params['dest'],
        count=params['count'],
        timeout=params['timeout'],
        ttl=params['ttl'],
        size=params['size'],
        source=params['source'],
        vrf=params['vrf']
    )

    # Execute ping command
    try:
        ping_results = run_commands(module, [ping_cmd])
    except ConnectionError as exc:
        module.fail_json(msg=str(exc))

    # Parse ping results
    ping_output = '\n'.join(ping_results)

    # Find the summary line - look for "Success" or "Sending" lines
    summary_line = ""
    for line in ping_output.split('\n'):
        if line.strip().startswith('Success') or line.strip().startswith('Sending'):
            summary_line = line.strip()
            break

    if not summary_line:
        # If no summary found, create a fallback based on the count
        summary_line = "Sending {0}, received 0".format(params['count'])

    # Parse the summary line
    success_percent, rx, tx, rtt_stats = parse_ping(summary_line)

    # Calculate packet loss
    success_rate = int(success_percent)
    packet_loss = 100 - success_rate

    # Prepare results
    result.update({
        'packets_tx': int(tx),
        'packets_rx': int(rx),
        'packet_loss': '{0}%'.format(packet_loss),
        'rtt': rtt_stats
    })

    # State validation
    if params['state'] == 'present':
        # Expect successful ping (0% packet loss)
        if packet_loss == 100:
            module.fail_json(msg='Ping failed unexpectedly', **result)
    elif params['state'] == 'absent':
        # Expect failed ping (100% packet loss)
        if packet_loss < 100:
            module.fail_json(msg='Ping succeeded unexpectedly', **result)

    module.exit_json(**result)


if __name__ == '__main__':
    main()