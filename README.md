# 🦋 ZooKeeper-like Distributed Coordination System
# *A lightweight, educational replica of ZooKeeper with leader election, log replication, and fault tolerance.*

This project implements a simplified version of the ZooKeeper Atomic Broadcast (ZAB) model.
It demonstrates how distributed systems maintain consistency, order, and availability through:

- Leader Election
- State & Log Replication
- Quorum-based Commits
- Fault Detection & Recovery
- A distributed Number Guessing Game to visualize state updates

Ideal for learning how real-world systems like ZooKeeper, etcd, and Consul coordinate distributed nodes.

# 📌 Features

##  Core System
- Dynamic Leader Election
- ZAB-style Log Replication
- Quorum Commit Mechanism
- Crash Detection & Automatic Recovery
- Cluster State Synchronization

##  Interactive Game Layer
A simple distributed game to demonstrate replicated state behavior:

- First client sets the target number (0–100)
- Other clients submit guesses
- The closest guess becomes the new global target
- Every update is replicated and committed across the cluster

##  Optional Visualization
The included `index.html` file provides a minimal interface to visualize node status.
The backend works fully standalone.

#  Quick Start

## 1. Start the Cluster (Backend)
Launch five nodes, each in its own terminal:

python zookeeper_server.py node 0
python zookeeper_server.py node 1
python zookeeper_server.py node 2
python zookeeper_server.py node 3
python zookeeper_server.py node 4

Nodes will automatically:
- Discover each other
- Elect a leader
- Begin log/state replication

## 2. Optional: Open the Visualization
Simply open:

index.html

This provides a lightweight cluster overview.

## 3. Simulate a Leader Crash
To test fault tolerance:

Ctrl + C   # in the leader’s terminal

The cluster will:
- Detect the crash
- Re-elect a leader
- Continue serving requests

#  Game Rules (Distributed Number Guessing)

- First client sets a target number (0–100)
- Other clients guess
- The closest guess becomes the new target
- Update is broadcast, replicated, and committed on all nodes

# 📁 Project Structure

.
├── zookeeper_server.py      # Distributed node implementation
├── index.html               # Optional visualization
├── README.md                # Documentation
└── logs/                    # Optional log output

# 🛠️ Technologies & Concepts

- Python
- Socket-based communication
- Distributed consensus
- Leader-based coordination
- Quorum voting
- Fault-tolerant replication
- Basic recovery mechanisms

# 📘 Purpose

Perfect for:
- Students learning distributed systems
- Classroom demos
- Understanding ZooKeeper internals
- Experimenting with replication & consensus models
