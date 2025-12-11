# 🧑🏻‍🌾 Apache ZooKeeper-like Distributed Coordination System

A lightweight educational implementation inspired by ZooKeeper, featuring leader election, log replication, and basic fault tolerance.

This project demonstrates core distributed-systems principles using a simplified version of the ZooKeeper Atomic Broadcast (ZAB) model.  
It illustrates how a cluster maintains consistency and availability through:

- Leader election
- State and log replication
- Quorum-based commits
- Fault detection and recovery
- A small distributed number-guessing game to visualize state updates

It serves as a practical introduction to coordination services such as ZooKeeper, etcd, and Consul.

# Features

## Core System
- Dynamic leader election
- ZAB-style log replication
- Quorum commit mechanism
- Crash detection and automated recovery
- Cluster state synchronization

## Interactive Game Layer
A minimal distributed game designed to show replicated state behavior:

- The first client sets a target number (0–100)
- Other clients submit guesses
- The closest guess becomes the new global target
- All updates are replicated and committed across the cluster

## Optional Visualization
The included `index.html` file provides a simple interface for visualizing node states.  
The backend operates fully independently and does not rely on the UI.

# Quick Start

## 1. Start the Cluster (Backend)
Start five nodes, each in its own terminal:

python zookeeper_server.py node 0
python zookeeper_server.py node 1
python zookeeper_server.py node 2
python zookeeper_server.py node 3
python zookeeper_server.py node 4

Each node will:
- Discover peer nodes
- Participate in leader election
- Begin log and state replication

## 2. Optional: UI Visualization
Open the file:

index.html

This provides a basic view of the cluster and the committed values.

## 3. Simulating a Leader Crash
To test failure handling, stop the current leader process:

Ctrl + C

The cluster will:
- Detect the failure
- Trigger a new leader election
- Resume normal operation

# Game Rules (Distributed Number Guessing)

- The first client selects a target number (0–100)
- Other clients propose guesses
- The closest guess becomes the new committed target
- The state is broadcast and replicated across all nodes

# Project Structure

- zookeeper_server.py      # Node implementation
- index.html               # Optional visualization tool
- README.md                # Project documentation
- logs/                    # Optional log output directory


# Project Purpose

This project is intended for:
- Students learning distributed systems
- Demonstrations and teaching material
- Understanding ZooKeeper-inspired coordination
- Experimentation with replication and consensus concepts
