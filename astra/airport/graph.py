"""
AEON Simulation - Graph / Routing Engine
Loads vvts_layout.json and provides Dijkstra shortest-path routing.
"""
import json
import math
import heapq
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ── Data classes ────────────────────────────────────────────
@dataclass
class Node:
    id: str
    name: str
    type: str          # 'wp' | 'stand' | 'hold'
    x: float
    y: float

@dataclass
class PathSegment:
    id: str
    name: str
    type: str          # 'runway' | 'taxiway'
    node_ids: List[str]

@dataclass
class Edge:
    to: str
    dist: float
    path_name: str
    path_type: str     # 'runway' | 'taxiway'


# ── Key node IDs (fixed in layout) ──────────────────────────
KEY_NODES = {
    'RWY25L_START' : 'n123',   # WP-1  — aircraft enters RWY 25L here
    'RWY25L_END'   : 'n124',   # WP-2  — end of RWY 25L (departed)
    'RWY25R_SPAWN' : 'n125',   # WP-3  — arrival aircraft spawns here
    'RWY25R_EXIT_P5': 'n175',  # WP-p5 — rapid exit via TWY P5
    'RWY25R_EXIT_P4': 'n126',  # WP-4  — alternate exit via TWY P
    'HLD_S1'       : 'n107',   # HLD-S1 — holding point before 25L
    'HLD_P5'       : 'n113',   # HLD-P5 — holding point P5 side
}


# ── AIP taxi routes (departure) ─────────────────────────────
# Derived from AIP table: stand group → AIP route label
AIP_DEP_ROUTES = {
    # stand_name : AIP route hint (informational only)
    **{f'S-0{i}': 'TWYs S, S1'        for i in range(1, 9)},
    'S-1A'       : 'TWYs S, S1',
    **{f'S-{i}':  'TWYs V, S3, S, S1' for i in range(9, 16)},
    **{f'S-{i}':  'TWYs S5, S, S1'    for i in range(17, 33)},
    **{f'S-{i}':  'Taxilane Y1, TWYs S6, S, S1' for i in range(33, 37)},
    **{f'S-{i}':  'Taxilane Y1, TWYs S5, S, S1' for i in range(37, 41)},
    **{f'S-{i}':  'TWYs S5, S, S1'    for i in range(41, 47)},
    **{f'S-{i}':  'TWYs V, S6, S, S1' for i in range(71, 87)},
    **{f'S-{i}':  'Taxilanes Y, Y1, TWYs S6, S, S1' for i in range(91, 105)},
    'S-103'      : 'Taxilanes V, S6, S, S1',
    'S-104'      : 'Taxilanes V, S6, S, S1',
}


# ── Airport Graph ────────────────────────────────────────────
class AirportGraph:
    def __init__(self, json_path: str):
        self.nodes: Dict[str, Node] = {}
        self.paths: List[PathSegment] = []
        self.adj: Dict[str, List[Edge]] = defaultdict(list)
        self._load(json_path)

    def _load(self, path: str):
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        for n in data['nodes']:
            self.nodes[n['id']] = Node(
                id=n['id'], name=n['name'],
                type=n['type'], x=n['x'], y=n['y']
            )

        for p in data['paths']:
            seg = PathSegment(
                id=p['id'], name=p['name'],
                type=p['type'], node_ids=p['ids']
            )
            self.paths.append(seg)

            ids = p['ids']
            for i in range(len(ids) - 1):
                a, b = ids[i], ids[i + 1]
                if a not in self.nodes or b not in self.nodes:
                    continue
                dx = self.nodes[a].x - self.nodes[b].x
                dy = self.nodes[a].y - self.nodes[b].y
                dist = math.hypot(dx, dy)
                self.adj[a].append(Edge(b, dist, p['name'], p['type']))
                self.adj[b].append(Edge(a, dist, p['name'], p['type']))

        # The source chart draws S8 across 25L without a shared graph node.
        # Connect the crossing to the existing runway-end node so occupancy
        # and crossing clearances apply to the real P5 exit path.
        for a,b in [('n113','n112'),('n112','n113')]:
            self.adj[a]=[e for e in self.adj[a] if e.to!=b]
        for a,b in [('n113','n124'),('n124','n112')]:
            for u,v in [(a,b),(b,a)]:
                distance=math.hypot(self.nodes[u].x-self.nodes[v].x,self.nodes[u].y-self.nodes[v].y)
                self.adj[u].append(Edge(v,distance,'TWY-S8.1','taxiway'))
        for path in self.paths:
            if path.name=='TWY-S8.1' and 'n124' not in path.node_ids:
                index=path.node_ids.index('n113');path.node_ids.insert(index+1,'n124')

    def node(self, nid: str) -> Optional[Node]:
        return self.nodes.get(nid)

    def node_by_name(self, name: str) -> Optional[Node]:
        for n in self.nodes.values():
            if n.name == name:
                return n
        return None

    def stands(self) -> List[Node]:
        return [n for n in self.nodes.values() if n.type == 'stand']

    def holding_points(self) -> List[Node]:
        return [n for n in self.nodes.values() if n.type == 'hold']

    # ── Dijkstra ────────────────────────────────────────────
    def dijkstra(
        self,
        start: str,
        end: str,
        forbidden: Optional[set] = None,
        penalty: Optional[Dict[str, float]] = None,
    ) -> Tuple[List[str], float]:
        """
        Returns (path_node_ids, total_distance).
        forbidden : set of node IDs to avoid entirely.
        penalty   : dict {node_id: extra_cost} for soft avoidance.
        """
        if forbidden is None:
            forbidden = set()
        if penalty is None:
            penalty = {}

        dist = {start: 0.0}
        prev: Dict[str, Optional[str]] = {start: None}
        pq = [(0.0, start)]

        while pq:
            d, u = heapq.heappop(pq)
            if u == end:
                break
            if d > dist.get(u, math.inf):
                continue
            for edge in self.adj.get(u, []):
                v = edge.to
                if v in forbidden:
                    continue
                nd = d + edge.dist + penalty.get(v, 0.0)
                if nd < dist.get(v, math.inf):
                    dist[v] = nd
                    prev[v] = u
                    heapq.heappush(pq, (nd, v))

        # Reconstruct
        path = []
        cur: Optional[str] = end
        while cur is not None:
            path.append(cur)
            cur = prev.get(cur)
        path.reverse()

        if not path or path[0] != start:
            return [], math.inf
        return path, dist.get(end, math.inf)

    def path_distance(self, node_ids: List[str]) -> float:
        total = 0.0
        for i in range(len(node_ids) - 1):
            a, b = node_ids[i], node_ids[i + 1]
            na, nb = self.nodes.get(a), self.nodes.get(b)
            if na and nb:
                total += math.hypot(na.x - nb.x, na.y - nb.y)
        return total
