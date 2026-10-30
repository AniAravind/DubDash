"""Serial named-destination missions over Nav2; no automatic restart or takeover."""
import json
import math
from pathlib import Path
import time

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from rclpy.qos import QoSProfile, DurabilityPolicy
from nav2_msgs.action import NavigateToPose
from action_msgs.msg import GoalStatus
from lifecycle_msgs.msg import State
from lifecycle_msgs.srv import GetState
from std_msgs.msg import Bool, String
from dubdash.missions import destinations, command, MissionLedger


class MissionManager(Node):
    def __init__(self):
        super().__init__('mission_manager')
        catalog = self.declare_parameter('destinations', '').value
        self.places = destinations(json.loads(Path(catalog).read_text()))
        self.ledger = MissionLedger(self.declare_parameter('ledger', ':memory:').value)
        self.max_duration = self.declare_parameter('leg_timeout', 300.0).value
        if not math.isfinite(self.max_duration) or self.max_duration <= 0:
            raise ValueError('leg_timeout must be finite and positive')
        self.client = ActionClient(self, NavigateToPose, '/navigate_to_pose')
        self.lifecycle = self.create_client(GetState, '/bt_navigator/get_state')
        self.nav2_active, self.nav2_stamp, self.state_request = False, -math.inf, None
        self.next_check = 0.
        self.publisher = self.create_publisher(String, '/missions/status',
            QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.permit = self.create_publisher(Bool, '/missions/permit', 1)
        self.create_subscription(String, '/missions/command', self.receive, 10)
        self.create_subscription(Bool, '/system/healthy', lambda m: self.health('system', m), 1)
        self.create_subscription(Bool, '/perception/healthy', lambda m: self.health('perception', m), 1)
        self.inputs = {}
        self.state, self.reason, self.route, self.index = 'idle', 'Explicit start required', [], 0
        self.mission_id, self.reply, self.goal_handle = None, None, None
        self.pending, self.stopping, self.deadline = False, False, 0.
        self.cancel_deadline = 0.
        self.distance = None
        self.create_timer(.05, self.tick)
        self.ledger.event(self.snapshot())
        self.publish()

    def health(self, name, msg):
        self.inputs[name] = (msg.data, time.monotonic())

    def ready(self):
        now = time.monotonic()
        return self.nav2_active and 0 <= now-self.nav2_stamp <= 2. and all(self.inputs.get(name, (False, -math.inf))[0]
            and 0 <= now-self.inputs[name][1] <= .25 for name in ('system', 'perception'))

    def snapshot(self):
        return dict(state=self.state, reason=self.reason, mission_id=self.mission_id,
            stamp_ns=self.get_clock().now().nanoseconds,
            route=self.route, completed_stops=self.index,
            destination=self.route[self.index] if self.index < len(self.route) else None,
            distance_remaining=self.distance, last_reply=self.reply,
            ready=self.ready(), nav2_active=self.nav2_active)

    def publish(self):
        self.publisher.publish(String(data=json.dumps(self.snapshot())))

    def transition(self, state, reason):
        self.state, self.reason = state, reason
        self.ledger.event(self.snapshot())
        self.publish()

    def receive(self, msg):
        request_id = None
        try:
            if len(msg.data) > 16384:
                raise ValueError('Command too large')
            payload = json.loads(msg.data)
            if isinstance(payload, dict):
                request_id = payload.get('request_id')
            request = command(payload, self.places)
            previous = self.ledger.previous(request)
            if previous is not None:
                self.reply = previous
                self.publish()
                return
            if request['operation'] == 'start':
                accepted = not (self.pending or self.goal_handle) and self.state not in ('dispatching', 'running', 'canceling', 'fault')
                accepted = accepted and self.ready() and self.client.server_is_ready()
                reason = 'Accepted' if accepted else 'Busy, unhealthy, faulted or Nav2 unavailable'
            else:
                accepted, reason = True, 'Cancellation requested'
            self.reply = dict(request_id=request_id, accepted=bool(accepted), message=reason)
            # Persist acknowledgement BEFORE dispatch. A crash cannot replay a start.
            self.ledger.record(request, self.reply)
            if accepted and request['operation'] == 'start':
                self.mission_id, self.route, self.index = request_id, request['route'], 0
                self.stopping = False
                self.dispatch()
            elif accepted:
                self.stop('Canceled by operator')
        except (ValueError, TypeError, KeyError, OSError) as error:
            self.reply = dict(request_id=request_id, accepted=False, message=str(error))
        self.publish()

    def dispatch(self):
        if not self.ready():
            self.transition('failed', 'Health lost before next stop; explicit new start required')
            return
        place = self.places[self.route[self.index]]
        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = 'map'
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.pose.position.x, goal.pose.pose.position.y = float(place['x']), float(place['y'])
        goal.pose.pose.orientation.z = math.sin(place['yaw']/2)
        goal.pose.pose.orientation.w = math.cos(place['yaw']/2)
        self.pending, self.distance = True, None
        self.deadline = time.monotonic()+self.max_duration
        self.transition('dispatching', 'Waiting for Nav2 acceptance')
        try:
            future = self.client.send_goal_async(goal, feedback_callback=self.feedback)
            future.add_done_callback(self.accepted)
        except Exception as error:
            self.pending = False
            self.transition('fault', f'Could not submit goal; restart required: {error}')

    def feedback(self, msg):
        value = float(msg.feedback.distance_remaining)
        self.distance = value if math.isfinite(value) else None

    def accepted(self, future):
        self.pending = False
        try:
            self.goal_handle = future.result()
            if not self.goal_handle.accepted:
                self.goal_handle = None
                self.transition('canceled' if self.stopping else 'failed', 'Nav2 rejected goal')
                return
            self.goal_handle.get_result_async().add_done_callback(self.finished)
            if self.stopping or not self.ready():
                self.stop('Stopped while goal acceptance was pending')
            else:
                self.transition('running', 'Navigating')
        except Exception as error:
            self.transition('fault', f'Goal acceptance failed; restart required: {error}')

    def finished(self, future):
        try:
            status = future.result().status
            self.goal_handle = None
            if self.stopping:
                self.transition('canceled', self.reason)
            elif status != GoalStatus.STATUS_SUCCEEDED:
                self.transition('failed', f'Nav2 result status {status}; explicit new start required')
            else:
                self.index += 1
                if self.index == len(self.route):
                    self.transition('succeeded', 'All destinations reached')
                else:
                    self.dispatch()
        except Exception as error:
            self.transition('fault', f'Goal result unavailable; restart required: {error}')

    def stop(self, reason):
        self.stopping = True
        self.cancel_deadline = time.monotonic()+5.
        self.permit.publish(Bool(data=False))
        self.transition('canceling' if self.pending or self.goal_handle else 'canceled', reason)
        if self.goal_handle:
            handle = self.goal_handle
            # Repeated tick cancellation is avoided by state, not by discarding handle.
            try:
                handle.cancel_goal_async()
            except Exception as error:
                self.transition('fault', f'Cancellation unavailable; restart required: {error}')

    def tick(self):
        now = time.monotonic()
        if now >= self.next_check and self.state_request is None and self.lifecycle.service_is_ready():
            self.next_check = now+.5
            self.state_request = self.lifecycle.call_async(GetState.Request())
            self.state_request.add_done_callback(self.navigation_state)
        active = self.state in ('dispatching', 'running')
        if active and (not self.ready() or time.monotonic() > self.deadline):
            self.stop('Health lost or leg timeout; explicit new start required')
        if self.state == 'canceling' and now > self.cancel_deadline:
            self.transition('fault', 'Cancellation not confirmed; permission remains blocked')
        self.permit.publish(Bool(data=self.state == 'running' and self.ready()))
        self.publish()

    def navigation_state(self, future):
        self.state_request = None
        try:
            self.nav2_active = future.result().current_state.id == State.PRIMARY_STATE_ACTIVE
            self.nav2_stamp = time.monotonic()
        except Exception:
            self.nav2_active = False

    def destroy_node(self):
        if rclpy.ok():
            self.permit.publish(Bool(data=False))
            if self.goal_handle:
                self.goal_handle.cancel_goal_async()
        self.client.destroy()
        self.ledger.close()
        return super().destroy_node()


def main(args=None):
    from dubdash.runtime import run
    run(MissionManager, args)
