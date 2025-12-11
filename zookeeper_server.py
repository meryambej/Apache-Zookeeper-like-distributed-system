#!/usr/bin/env python3
"""
Complete ZooKeeper-like Distributed System Backend
Author: Distributed Systems Lab 4
Date: 2025

Features:
- Leader election with heartbeat monitoring
- ZAB protocol (proposal, ACK, commit)
- Log replication with persistence
- Automatic failover and recovery
- Multi-threaded server handling
"""

import socket
import threading
import json
import time
import sys
import os
import pickle
from enum import Enum
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Tuple
from collections import defaultdict


# ============================================================================
# MESSAGE TYPES AND DATA STRUCTURES
# ============================================================================

class MessageType(Enum):
    """All message types in the system"""
    # Client operations
    WRITE = "WRITE"
    GUESS = "GUESS"
    READ = "READ"
    
    # ZAB protocol
    PROPOSE = "PROPOSE"
    ACK = "ACK"
    COMMIT = "COMMIT"
    
    # Leader election
    HEARTBEAT = "HEARTBEAT"
    ELECTION = "ELECTION"
    VOTE = "VOTE"
    LEADER_ANNOUNCE = "LEADER_ANNOUNCE"
    
    # Responses
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    INFO = "INFO"


@dataclass
class LogEntry:
    """Single log entry with ZAB metadata"""
    epoch: int
    seq: int
    operation: str  # WRITE, GUESS
    value: int
    status: str  # PROPOSED, COMMITTED
    client_id: Optional[str] = None
    timestamp: float = 0.0

    def to_dict(self):
        return asdict(self)


@dataclass
class Message:
    """Message format for node communication"""
    msg_type: MessageType
    sender_id: int
    data: dict
    
    def to_json(self) -> str:
        return json.dumps({
            'msg_type': self.msg_type.value,
            'sender_id': self.sender_id,
            'data': self.data
        })
    
    @staticmethod
    def from_json(json_str: str) -> 'Message':
        obj = json.loads(json_str)
        return Message(
            MessageType(obj['msg_type']),
            obj['sender_id'],
            obj['data']
        )


# ============================================================================
# NODE CLASS - CORE DISTRIBUTED SYSTEM LOGIC
# ============================================================================

class Node:
    """
    Distributed node implementing ZooKeeper-like consensus
    """
    
    def __init__(self, node_id: int, port: int, all_nodes_info: List[Tuple[int, str, int]]):
        # Identity
        self.node_id = node_id
        self.port = port
        self.all_nodes = all_nodes_info
        
        # Role and state
        self.role = 'leader' if node_id == 0 else 'follower'
        self.epoch = 1
        self.seq = 0
        self.current_target = None
        self.pending_guesses = []
        
        # Log management
        self.log: List[LogEntry] = []
        self.log_file = f"data/node_{node_id}_log.pkl"
        self._ensure_data_dir()
        self.load_log()
        
        # Leader election
        self.leader_id = 0 if node_id != 0 else node_id
        self.last_heartbeat = time.time()
        self.election_timeout = 5.0
        self.heartbeat_interval = 2.0
        self.in_election = False
        
        # Networking
        self.server_socket = None
        self.running = True
        self.ack_count = defaultdict(int)
        self.ack_lock = threading.Lock()
        self.state_lock = threading.Lock()
        
        # Statistics
        self.stats = {
            'messages_received': 0,
            'proposals_created': 0,
            'commits_applied': 0,
            'elections_participated': 0
        }
        
        self._log(f"Initialized as {self.role.upper()} on port {port}")
    
    def _ensure_data_dir(self):
        """Create data directory if not exists"""
        os.makedirs('data', exist_ok=True)
    
    def _log(self, message: str, level: str = "INFO"):
        """Pretty logging"""
        timestamp = time.strftime("%H:%M:%S")
        role_color = "🟡" if self.role == 'leader' else "🔵" if self.role == 'follower' else "🟠"
        print(f"[{timestamp}] {role_color} Node {self.node_id} ({self.role}): {message}")
    
    # ========================================================================
    # LOG PERSISTENCE
    # ========================================================================
    
    def load_log(self):
        """Load log from disk"""
        if os.path.exists(self.log_file):
            try:
                with open(self.log_file, 'rb') as f:
                    data = pickle.load(f)
                    self.log = [LogEntry(**entry) if isinstance(entry, dict) else entry for entry in data]
                self._log(f"Loaded {len(self.log)} log entries from disk")
                
                # Restore state from committed entries
                for entry in self.log:
                    if entry.status == 'COMMITTED':
                        self.seq = max(self.seq, entry.seq)
                        self.epoch = max(self.epoch, entry.epoch)
                        if entry.operation in ['WRITE', 'GUESS']:
                            self.current_target = entry.value
            except Exception as e:
                self._log(f"Error loading log: {e}", "ERROR")
                self.log = []
    
    def save_log(self):
        """Persist log to disk"""
        try:
            with open(self.log_file, 'wb') as f:
                pickle.dump([entry.to_dict() for entry in self.log], f)
        except Exception as e:
            self._log(f"Error saving log: {e}", "ERROR")
    
    # ========================================================================
    # SERVER LIFECYCLE
    # ========================================================================
    
    def start(self):
        """Start the node server"""
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind(('localhost', self.port))
            self.server_socket.listen(20)
            
            # Start threads
            threading.Thread(target=self.accept_connections, daemon=True, name="AcceptThread").start()
            
            if self.role == 'leader':
                threading.Thread(target=self.send_heartbeats, daemon=True, name="HeartbeatThread").start()
            else:
                threading.Thread(target=self.check_heartbeat, daemon=True, name="MonitorThread").start()
            
            self._log(f"✅ Server started on port {self.port}")
            
        except Exception as e:
            self._log(f"Failed to start: {e}", "ERROR")
            sys.exit(1)
    
    def accept_connections(self):
        """Accept and handle incoming connections"""
        while self.running:
            try:
                client_socket, addr = self.server_socket.accept()
                threading.Thread(
                    target=self.handle_connection,
                    args=(client_socket,),
                    daemon=True,
                    name=f"Handler-{addr}"
                ).start()
            except Exception as e:
                if self.running:
                    self._log(f"Accept error: {e}", "ERROR")
    
    def handle_connection(self, client_socket: socket.socket):
        """Handle a single client connection"""
        try:
            data = client_socket.recv(8192).decode('utf-8')
            if not data:
                return
            
            self.stats['messages_received'] += 1
            msg = Message.from_json(data)
            response = self.process_message(msg)
            
            if response:
                client_socket.send(response.to_json().encode('utf-8'))
                
        except Exception as e:
            self._log(f"Connection error: {e}", "ERROR")
        finally:
            try:
                client_socket.close()
            except:
                pass
    
    # ========================================================================
    # MESSAGE PROCESSING ROUTER
    # ========================================================================
    
    def process_message(self, msg: Message) -> Optional[Message]:
        """Route message to appropriate handler"""
        handlers = {
            MessageType.WRITE: self.handle_write,
            MessageType.GUESS: self.handle_guess,
            MessageType.READ: self.handle_read,
            MessageType.PROPOSE: self.handle_propose,
            MessageType.ACK: self.handle_ack,
            MessageType.COMMIT: self.handle_commit,
            MessageType.HEARTBEAT: self.handle_heartbeat,
            MessageType.ELECTION: self.handle_election,
            MessageType.VOTE: self.handle_vote,
            MessageType.LEADER_ANNOUNCE: self.handle_leader_announce,
        }
        
        handler = handlers.get(msg.msg_type)
        if handler:
            return handler(msg)
        
        return Message(MessageType.ERROR, self.node_id, {'error': 'Unknown message type'})
    
    # ========================================================================
    # CLIENT REQUEST HANDLERS
    # ========================================================================
    
    def handle_write(self, msg: Message) -> Message:
        """Handle WRITE request to set target"""
        value = msg.data['value']
        client_id = msg.data.get('client_id', 'unknown')
        
        self._log(f"📝 Received WRITE({value}) from {client_id}")
        
        if self.role == 'leader':
            self.create_proposal('WRITE', value, client_id)
            return Message(MessageType.SUCCESS, self.node_id, 
                         {'message': 'Proposal initiated'})
        else:
            self._log(f"🔄 Forwarding WRITE to leader {self.leader_id}")
            response = self.send_to_node(self.leader_id, Message(
                MessageType.WRITE, self.node_id,
                {'value': value, 'client_id': client_id}
            ))
            return Message(MessageType.SUCCESS, self.node_id,
                         {'message': 'Forwarded to leader'})
    
    def handle_guess(self, msg: Message) -> Message:
        """Handle GUESS request"""
        value = msg.data['value']
        client_id = msg.data.get('client_id', 'unknown')
        
        if self.current_target is None:
            return Message(MessageType.ERROR, self.node_id,
                         {'error': 'No target set yet'})
        
        distance = abs(value - self.current_target)
        self._log(f"🎯 Received GUESS({value}) from {client_id}, distance={distance}")
        
        if self.role == 'leader':
            self.pending_guesses.append({
                'client_id': client_id,
                'value': value,
                'distance': distance
            })
            
            # Process immediately (simplified)
            if self.pending_guesses:
                closest = min(self.pending_guesses, key=lambda x: x['distance'])
                self.pending_guesses.clear()
                
                self._log(f"🏆 Closest: {closest['value']} from {closest['client_id']}")
                self.create_proposal('GUESS', closest['value'], closest['client_id'])
            
            return Message(MessageType.SUCCESS, self.node_id,
                         {'message': f'Guess received, distance: {distance}'})
        else:
            self.send_to_node(self.leader_id, Message(
                MessageType.GUESS, self.node_id,
                {'value': value, 'client_id': client_id}
            ))
            return Message(MessageType.SUCCESS, self.node_id,
                         {'message': 'Forwarded to leader'})
    
    def handle_read(self, msg: Message) -> Message:
        """Handle READ request"""
        return Message(MessageType.INFO, self.node_id, {
            'target': self.current_target,
            'epoch': self.epoch,
            'seq': self.seq,
            'role': self.role,
            'log_size': len(self.log)
        })
    
    # ========================================================================
    # ZAB PROTOCOL - PROPOSAL PHASE
    # ========================================================================
    
    def create_proposal(self, operation: str, value: int, client_id: str):
        """Leader creates and broadcasts proposal"""
        if self.role != 'leader':
            return
        
        with self.state_lock:
            self.seq += 1
            entry = LogEntry(
                epoch=self.epoch,
                seq=self.seq,
                operation=operation,
                value=value,
                status='PROPOSED',
                client_id=client_id,
                timestamp=time.time()
            )
            self.log.append(entry)
            self.save_log()
            self.stats['proposals_created'] += 1
            
            proposal_key = f"{entry.epoch}-{entry.seq}"
            with self.ack_lock:
                self.ack_count[proposal_key] = 1  # Leader's ACK
            
            self._log(f"📋 PROPOSAL: epoch={entry.epoch}, seq={entry.seq}, op={operation}, val={value}")
        
        # Broadcast to followers
        propose_msg = Message(MessageType.PROPOSE, self.node_id, {
            'epoch': entry.epoch,
            'seq': entry.seq,
            'operation': operation,
            'value': value,
            'client_id': client_id
        })
        
        for node_id, host, port in self.all_nodes:
            if node_id != self.node_id:
                threading.Thread(
                    target=self.send_to_node,
                    args=(node_id, propose_msg),
                    daemon=True,
                    name=f"Propose-{node_id}"
                ).start()
    
    def handle_propose(self, msg: Message) -> Optional[Message]:
        """Follower handles proposal"""
        if self.role == 'leader':
            return None
        
        with self.state_lock:
            entry = LogEntry(
                epoch=msg.data['epoch'],
                seq=msg.data['seq'],
                operation=msg.data['operation'],
                value=msg.data['value'],
                status='PROPOSED',
                client_id=msg.data.get('client_id'),
                timestamp=time.time()
            )
            self.log.append(entry)
            self.save_log()
            
            self._log(f"✅ Logged PROPOSAL: epoch={entry.epoch}, seq={entry.seq}")
        
        # Send ACK
        ack_msg = Message(MessageType.ACK, self.node_id, {
            'epoch': entry.epoch,
            'seq': entry.seq
        })
        self.send_to_node(msg.sender_id, ack_msg)
        return None
    
    # ========================================================================
    # ZAB PROTOCOL - ACK AND COMMIT PHASE
    # ========================================================================
    
    def handle_ack(self, msg: Message) -> Optional[Message]:
        """Leader handles ACK from follower"""
        if self.role != 'leader':
            return None
        
        epoch = msg.data['epoch']
        seq = msg.data['seq']
        proposal_key = f"{epoch}-{seq}"
        
        with self.ack_lock:
            if proposal_key in self.ack_count:
                self.ack_count[proposal_key] += 1
                acks = self.ack_count[proposal_key]
                quorum = len(self.all_nodes) // 2 + 1
                
                self._log(f"✅ ACK received for {proposal_key}: {acks}/{len(self.all_nodes)} (quorum={quorum})")
                
                if acks >= quorum:
                    self._log(f"🎯 QUORUM REACHED for {proposal_key}!")
                    del self.ack_count[proposal_key]
                    threading.Thread(
                        target=self.broadcast_commit,
                        args=(epoch, seq),
                        daemon=True,
                        name=f"Commit-{proposal_key}"
                    ).start()
        
        return None
    
    def broadcast_commit(self, epoch: int, seq: int):
        """Leader broadcasts COMMIT after quorum"""
        commit_msg = Message(MessageType.COMMIT, self.node_id, {
            'epoch': epoch,
            'seq': seq
        })
        
        # Apply locally first
        self.apply_commit(epoch, seq)
        
        # Broadcast to followers
        for node_id, host, port in self.all_nodes:
            if node_id != self.node_id:
                self.send_to_node(node_id, commit_msg)
    
    def handle_commit(self, msg: Message) -> Optional[Message]:
        """Handle COMMIT message"""
        epoch = msg.data['epoch']
        seq = msg.data['seq']
        self._log(f"🎯 Received COMMIT: epoch={epoch}, seq={seq}")
        self.apply_commit(epoch, seq)
        return None
    
    def apply_commit(self, epoch: int, seq: int):
        """Apply committed entry to state"""
        with self.state_lock:
            for entry in self.log:
                if entry.epoch == epoch and entry.seq == seq and entry.status == 'PROPOSED':
                    entry.status = 'COMMITTED'
                    
                    if entry.operation in ['WRITE', 'GUESS']:
                        self.current_target = entry.value
                        self._log(f"✨ COMMITTED: New target = {entry.value}")
                    
                    self.stats['commits_applied'] += 1
                    self.save_log()
                    break
    
    # ========================================================================
    # LEADER ELECTION - HEARTBEAT
    # ========================================================================
    
    def send_heartbeats(self):
        """Leader sends periodic heartbeats"""
        while self.running and self.role == 'leader':
            time.sleep(self.heartbeat_interval)
            
            heartbeat_msg = Message(MessageType.HEARTBEAT, self.node_id, {
                'epoch': self.epoch,
                'seq': self.seq
            })
            
            for node_id, host, port in self.all_nodes:
                if node_id != self.node_id:
                    threading.Thread(
                        target=self.send_to_node,
                        args=(node_id, heartbeat_msg),
                        daemon=True,
                        name=f"Heartbeat-{node_id}"
                    ).start()
    
    def handle_heartbeat(self, msg: Message) -> Optional[Message]:
        """Follower handles heartbeat"""
        self.last_heartbeat = time.time()
        self.leader_id = msg.sender_id
        return None
    
    def check_heartbeat(self):
        """Follower monitors leader heartbeat"""
        while self.running:
            time.sleep(1)
            
            if self.role == 'follower' and not self.in_election:
                if time.time() - self.last_heartbeat > self.election_timeout:
                    self._log("⚠️  LEADER TIMEOUT! Starting election...", "WARN")
                    self.start_election()
    
    # ========================================================================
    # LEADER ELECTION - VOTING
    # ========================================================================
    
    def start_election(self):
        """Start leader election process"""
        if self.in_election:
            return
        
        self.in_election = True
        self.stats['elections_participated'] += 1
        
        with self.state_lock:
            self.role = 'candidate'
            self.epoch += 1
        
        self._log(f"🗳️  ELECTION STARTED for epoch {self.epoch}")
        
        # Request votes
        election_msg = Message(MessageType.ELECTION, self.node_id, {
            'epoch': self.epoch,
            'seq': self.seq
        })
        
        votes = [1]  # Self vote
        vote_lock = threading.Lock()
        
        def collect_vote(node_id):
            response = self.send_to_node(node_id, election_msg, timeout=2)
            if response and response.msg_type == MessageType.VOTE and response.data.get('vote'):
                with vote_lock:
                    votes[0] += 1
                    self._log(f"🗳️  Vote received from Node {node_id}")
        
        threads = []
        for node_id, host, port in self.all_nodes:
            if node_id != self.node_id:
                t = threading.Thread(target=collect_vote, args=(node_id,), daemon=True)
                t.start()
                threads.append(t)
        
        for t in threads:
            t.join(timeout=3)
        
        quorum = len(self.all_nodes) // 2 + 1
        
        with self.state_lock:
            if votes[0] >= quorum:
                self._log(f"👑 WON ELECTION with {votes[0]} votes!")
                self.become_leader()
            else:
                self._log(f"❌ Lost election with {votes[0]} votes")
                self.role = 'follower'
            
            self.in_election = False
    
    def handle_election(self, msg: Message) -> Message:
        """Handle election request"""
        candidate_epoch = msg.data['epoch']
        candidate_seq = msg.data['seq']
        
        # Vote if candidate is more up-to-date
        vote = (candidate_epoch > self.epoch or 
                (candidate_epoch == self.epoch and candidate_seq >= self.seq))
        
        if vote:
            self._log(f"🗳️  Voting YES for Node {msg.sender_id}")
        
        return Message(MessageType.VOTE, self.node_id, {'vote': vote})
    
    def handle_vote(self, msg: Message) -> Optional[Message]:
        """Handle vote response (processed in collect_vote)"""
        return None
    
    def become_leader(self):
        """Transition to leader role"""
        self.role = 'leader'
        self.leader_id = self.node_id
        
        # Announce leadership
        announce_msg = Message(MessageType.LEADER_ANNOUNCE, self.node_id, {
            'epoch': self.epoch
        })
        
        for node_id, host, port in self.all_nodes:
            if node_id != self.node_id:
                self.send_to_node(node_id, announce_msg)
        
        # Start heartbeats
        threading.Thread(target=self.send_heartbeats, daemon=True, name="HeartbeatThread").start()
        
        self._log("✨ Leadership established")
    
    def handle_leader_announce(self, msg: Message) -> Optional[Message]:
        """Handle leader announcement"""
        with self.state_lock:
            self.role = 'follower'
            self.leader_id = msg.sender_id
            self.epoch = msg.data['epoch']
            self.last_heartbeat = time.time()
        
        self._log(f"📢 Acknowledged Node {msg.sender_id} as leader (epoch {self.epoch})")
        return None
    
    # ========================================================================
    # NETWORK COMMUNICATION
    # ========================================================================
    
    def send_to_node(self, node_id: int, msg: Message, timeout: float = 3.0) -> Optional[Message]:
        """Send message to another node"""
        for nid, host, port in self.all_nodes:
            if nid == node_id:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(timeout)
                    sock.connect((host, port))
                    sock.send(msg.to_json().encode('utf-8'))
                    
                    response_data = sock.recv(8192).decode('utf-8')
                    sock.close()
                    
                    if response_data:
                        return Message.from_json(response_data)
                except Exception as e:
                    # Node might be down
                    pass
                break
        return None
    
    # ========================================================================
    # CLEANUP
    # ========================================================================
    
    def stop(self):
        """Stop node gracefully"""
        self._log("Shutting down...")
        self.running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
        self.save_log()


# ============================================================================
# CLIENT CLASS
# ============================================================================

class Client:
    """Client for interacting with the distributed system"""
    
    def __init__(self, client_id: int, name: str, node_host: str, node_port: int):
        self.client_id = client_id
        self.name = name
        self.node_host = node_host
        self.node_port = node_port
    
    def _send(self, msg: Message, timeout: float = 5.0) -> Optional[Message]:
        """Send request to connected node"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((self.node_host, self.node_port))
            sock.send(msg.to_json().encode('utf-8'))
            
            response_data = sock.recv(8192).decode('utf-8')
            sock.close()
            
            if response_data:
                return Message.from_json(response_data)
        except Exception as e:
            print(f"[{self.name}] ❌ Error: {e}")
        return None
    
    def write_target(self, value: int):
        """Set target value"""
        print(f"\n[{self.name}] 📝 Setting target to {value}")
        msg = Message(MessageType.WRITE, -1, {
            'value': value,
            'client_id': self.name
        })
        response = self._send(msg)
        if response:
            print(f"[{self.name}] ✅ {response.data.get('message', 'OK')}")
    
    def guess(self, value: int):
        """Submit a guess"""
        print(f"\n[{self.name}] 🎯 Guessing {value}")
        msg = Message(MessageType.GUESS, -1, {
            'value': value,
            'client_id': self.name
        })
        response = self._send(msg)
        if response:
            print(f"[{self.name}] ✅ {response.data.get('message', 'OK')}")
    
    def read_target(self):
        """Read current target"""
        msg = Message(MessageType.READ, -1, {})
        response = self._send(msg)
        if response and response.msg_type == MessageType.INFO:
            data = response.data
            print(f"\n[{self.name}] 📊 Status:")
            print(f"  Target: {data.get('target', 'Not set')}")
            print(f"  Epoch: {data.get('epoch')}")
            print(f"  Seq: {data.get('seq')}")
            print(f"  Node role: {data.get('role')}")
            return data.get('target')
        return None


# ============================================================================
# MAIN PROGRAM
# ============================================================================

def print_banner():
    """Print system banner"""
    print("\n" + "="*70)
    print("  🖥️  ZOOKEEPER-LIKE DISTRIBUTED SYSTEM")
    print("  Leader Election • ZAB Protocol • Fault Tolerance")
    print("="*70 + "\n")


def run_node(node_id: int):
    """Run a single node"""
    all_nodes = [
        (0, 'localhost', 5000),
        (1, 'localhost', 5001),
        (2, 'localhost', 5002),
        (3, 'localhost', 5003),
        (4, 'localhost', 5004)
    ]
    
    port = all_nodes[node_id][2]
    node = Node(node_id, port, all_nodes)
    node.start()
    
    print_banner()
    print(f"✅ Node {node_id} is running on port {port}")
    print(f"📋 Role: {node.role.upper()}")
    print(f"💾 Log file: {node.log_file}")
    print("\nPress Ctrl+C to stop\n")
    print("-" * 70 + "\n")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n\n🛑 Stopping Node {node_id}...")
        node.stop()
        print("✅ Stopped\n")


def run_test_scenarios():
    """Run automated test scenarios"""
    print_banner()
    print("🧪 RUNNING TEST SCENARIOS\n")
    
    # Wait for nodes to stabilize
    print("⏳ Waiting for nodes to initialize...")
    time.sleep(3)
    
    clients = [
        Client(0, 'Alice', 'localhost', 5000),
        Client(1, 'Bob', 'localhost', 5001),
        Client(2, 'Charlie', 'localhost', 5002),
        Client(3, 'Diana', 'localhost', 5003),
        Client(4, 'Eve', 'localhost', 5004)
    ]
    
    print("\n" + "="*70)
    print("TEST 1: Normal Write Flow (Quorum Commit)")
    print("="*70)
    clients[0].write_target(50)
    time.sleep(3)
    clients[1].read_target()
    
    print("\n" + "="*70)
    print("TEST 2: Guessing Flow")
    print("="*70)
    clients[1].guess(45)
    time.sleep(2)
    clients[2].guess(52)
    time.sleep(3)
    clients[3].read_target()
    
    print("\n" + "="*70)
    print("TEST 3: Leader Crash & Recovery")
    print("="*70)
    print("⚠️  To test leader crash:")
    print("1. Find the leader node terminal (usually Node 0)")
    print("2. Press Ctrl+C to stop it")
    print("3. Watch other terminals for election")
    print("4. Wait 5-10 seconds")
    print("5. Try operations again with new leader")
    print("="*70 + "\n")


def show_help():
    """Show help message"""
    print_banner()
    print("USAGE:")
    print("  python zookeeper_server.py node <id>    Start a node (id: 0-4)")
    print("  python zookeeper_server.py test         Run test scenarios")
    print("  python zookeeper_server.py help         Show this help")
    print("\nEXAMPLES:")
    print("  # Terminal 1: Start leader")
    print("  python zookeeper_server.py node 0")
    print("\n  # Terminal 2-5: Start followers")
    print("  python zookeeper_server.py node 1")
    print("  python zookeeper_server.py node 2")
    print("  python zookeeper_server.py node 3")
    print("  python zookeeper_server.py node 4")
    print("\n  # Terminal 6: Run tests")
    print("  python zookeeper_server.py test")
    print("\n" + "="*70 + "\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        show_help()
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == 'node':
        if len(sys.argv) < 3:
            print("❌ Error: Node ID required")
            print("Usage: python zookeeper_server.py node <id>")
            sys.exit(1)
        
        try:
            node_id = int(sys.argv[2])
            if node_id < 0 or node_id > 4:
                print("❌ Error: Node ID must be between 0 and 4")
                sys.exit(1)
            run_node(node_id)
        except ValueError:
            print("❌ Error: Node ID must be a number")
            sys.exit(1)
    
    elif command == 'test':
        run_test_scenarios()
    
    elif command == 'help':
        show_help()
    
    else:
        print(f"❌ Unknown command: {command}")
        show_help()
        sys.exit(1)