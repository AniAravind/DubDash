"""Send a mission command and wait for its acknowledgement, or inspect status."""
import argparse
import json
import time
import uuid
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy
from std_msgs.msg import String


def main(args=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['start', 'cancel', 'status'])
    parser.add_argument('route', nargs='*')
    parser.add_argument('--request-id', default=None)
    options, ros_args = parser.parse_known_args(args)
    if options.operation != 'start' and options.route:
        parser.error('Only start takes destination names')
    if options.operation == 'start' and not options.route:
        parser.error('Provide at least one named destination')
    request_id = options.request_id or uuid.uuid4().hex
    payload = dict(request_id=request_id, operation=options.operation, route=options.route)
    rclpy.init(args=ros_args)
    node = Node('mission_cli_'+uuid.uuid4().hex[:8])
    received = []
    def status(msg):
        value = json.loads(msg.data)
        if options.operation == 'status' or (value.get('last_reply') or {}).get('request_id') == request_id:
            received.append(value)
    node.create_subscription(String, '/missions/status', status,
        QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
    publisher = node.create_publisher(String, '/missions/command', 10)
    deadline, next_send = time.monotonic()+10, 0.
    try:
        while time.monotonic() < deadline and not received:
            if options.operation != 'status' and time.monotonic() >= next_send:
                publisher.publish(String(data=json.dumps(payload)))
                next_send = time.monotonic()+1.
            rclpy.spin_once(node, timeout_sec=.1)
        if not received:
            print(f'No acknowledgement. Request ID: {request_id}. Retry with the SAME ID; do not assume it failed.')
            raise SystemExit(2)
        print(json.dumps(received[-1], indent=2))
        if options.operation != 'status' and not received[-1]['last_reply']['accepted']:
            raise SystemExit(1)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
