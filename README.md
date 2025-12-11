-----------------------ZooKeeper-like Distributed System----------------
Fault-tolerant distributed system with leader election, ZAB protocol, and number guessing game.
1-Quick Start
- Frontend (Visualization) : 
double click index.html
- Backend (Full System) : 
--> Start 5 nodes (5 terminals)
#python zookeeper_server.py node 0
#python zookeeper_server.py node 1
#python zookeeper_server.py node 2
#python zookeeper_server.py node 3
#python zookeeper_server.py node 4
--> Simulating a Leader Crash
#To simulate a leader failure, simply terminate the leader node by pressing Ctrl + C in its terminal.
- Architecture : 
-----------------------------------------------------
Client → Follower → Leader → All Followers
                      ↓
                  Quorum (3/5)
                      ↓
                   COMMIT
---------------------------------------------------
ZAB Protocol: PROPOSE → ACK → COMMIT
Leader Election: Timeout → Vote → New Leader
Quorum: 3/5 nodes

Rq : Game Rules
- First client sets target (0-100)
- Others guess
- Closest guess = new target