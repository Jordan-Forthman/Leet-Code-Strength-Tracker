"""Topic taxonomy.

LeetCode tags (~170 of them, many very fine-grained like "Dijkstra's Algorithm")
are folded into ~20 interview-oriented *groups*. Ratings are tracked at both
levels: per raw tag (fine detail) and per group (what the dashboard leads with).

Each group carries an ``importance`` in [0, 1] describing how often that topic
shows up in entry-level coding assessments. The recommender uses it to decide
which weaknesses are worth drilling first.
"""

from __future__ import annotations

# (group name, importance, explicit member tags)
GROUPS: list[tuple[str, float, list[str]]] = [
    ("Arrays & Hashing", 1.0, [
        "Array", "Hash Table", "Hash Function", "Counting", "Prefix Sum",
        "Enumeration", "Simulation", "Matrix", "Pigeonhole Principle",
        "Boyer–Moore Majority Vote Algorithm",
    ]),
    ("Strings", 0.85, [
        "String", "String Matching", "Rolling Hash", "Knuth–Morris–Pratt Algorithm",
        "Z Algorithm", "Manacher", "Boyer–Moore String-Search Algorithm",
        "Aho–Corasick Algorithm", "Suffix Array", "Suffix Automaton", "Suffix Tree",
        "Palindromic Tree", "Lyndon Factorization",
        "Lexicographically Minimal String Rotation", "Bracket Sequences",
    ]),
    ("Two Pointers", 1.0, ["Two Pointers"]),
    ("Sliding Window", 1.0, ["Sliding Window", "Monotonic Queue"]),
    ("Stacks & Queues", 0.9, ["Stack", "Monotonic Stack", "Queue"]),
    ("Binary Search", 1.0, ["Binary Search", "Ternary Search"]),
    ("Sorting", 0.8, [
        "Sorting", "Sort", "Counting Sort", "Bucket Sort", "Radix Sort", "Merge Sort",
        "Quicksort", "Quickselect", "Bubble Sort", "Timsort", "Tournament Sort",
    ]),
    ("Linked List", 0.9, ["Linked List", "Doubly-Linked List", "Floyd's Cycle Finding Algorithm"]),
    ("Trees", 1.0, [
        "Tree", "Binary Tree", "Binary Search Tree", "Lowest Common Ancestor",
        "Binary Lifting", "Cartesian Tree", "DP on Trees",
    ]),
    ("Tries", 0.6, ["Trie"]),
    ("Heap / Priority Queue", 0.9, ["Heap (Priority Queue)", "Heap", "Data Stream"]),
    ("Backtracking & Recursion", 0.85, [
        "Backtracking", "Recursion", "Divide and Conquer", "Meet in the Middle",
        "Brute-Force Search", "Algorithm X", "Dancing Links",
    ]),
    ("Graphs", 1.0, [
        "Graph Theory", "Graph", "Depth-First Search", "Breadth-First Search",
        "Union-Find", "Union Find", "Topological Sort", "Directed Acyclic Graph",
        "Bipartite Graph", "Bidirectional Search", "0-1 BFS", "Graph Coloring",
    ]),
    ("Advanced Graphs", 0.5, [
        "Shortest Path", "Dijkstra's Algorithm", "Bellman–Ford Algorithm",
        "Floyd–Warshall Algorithm", "Minimum Spanning Tree", "Prim's Algorithm",
        "Kruskal's Algorithm", "Borůvka's Algorithm", "Eulerian Circuit",
        "Eulerian Path", "Eulerian Graph", "Semi-Eulerian Graph",
        "Strongly Connected Component", "Tarjan's SCC Algorithm", "Kosaraju's Algorithm",
        "Biconnected Component", "Bridge (Graph)", "Articulation Point",
        "Hamiltonian Path", "A* Search", "Heuristic Search", "K Shortest Path",
        "Planar Graph", "Flow Network", "Maximum Flow", "Minimum Cut",
        "Minimum-Cost Flow", "Edmonds–Karp Algorithm", "Dinic's Algorithm",
        "MPM Algorithm", "Push-Relabel Algorithm", "Successive Shortest Path Algorithm",
        "Matching (Graph)", "Maximum Matching", "Perfect Matching", "Hungarian Algorithm",
    ]),
    ("Dynamic Programming", 1.0, [
        "Dynamic Programming", "Memoization", "Knapsack Problem", "0-1 Knapsack",
        "Complete Knapsack", "Mixed Knapsack", "Multiple Knapsack",
        "Longest Increasing Subsequence", "Longest Common Subsequence",
    ]),
    ("Greedy", 0.9, ["Greedy"]),
    ("Math & Geometry", 0.55, [
        "Math", "Number Theory", "Combinatorics", "Geometry", "Probability and Statistics",
        "Greatest Common Divisor", "Least Common Multiple", "Euclidean Algorithm",
        "Extended Euclidean Algorithm", "Bézout's Lemma", "Prime Factorization",
        "Primality Test", "Sieve Theory", "Prime Number Sieve", "Fermat's Little Theorem",
        "Euler's Totient Function", "Euler's Theorem", "Inclusion-Exclusion Principle",
        "Linear Algebra", "Newton's Method", "Polygons", "Convex Hull", "Triangulation",
        "Minimum Enclosing Circle", "Game Theory", "Minimax", "Zero-Sum Game",
        "Impartial Game", "Nim Game", "Sprague–Grundy Theorem", "Brainteaser",
        "Randomized", "Reservoir Sampling", "Rejection Sampling",
    ]),
    ("Bit Manipulation", 0.6, ["Bit Manipulation", "Bitmask"]),
    ("Design", 0.75, ["Design", "Iterator", "Interactive"]),
    ("Advanced Data Structures", 0.3, [
        "Segment Tree", "Binary Indexed Tree", "Ordered Set", "Treap", "Splay Tree",
        "Sqrt Decomposition", "Persistent Data Structure", "K-D Tree", "Li Chao Tree",
        "Sparse Table", "Range Minimum/Maximum Query", "Sweep Line", "Line Sweep",
    ]),
]

OTHER_GROUP = "Other"
OTHER_IMPORTANCE = 0.2

# Fallback keyword rules for tags LeetCode adds in the future.
_KEYWORD_RULES: list[tuple[tuple[str, ...], str]] = [
    (("knapsack", "subsequence", "dp "), "Dynamic Programming"),
    (("graph", "path", "flow", "matching", "spanning", "euler", "bfs", "dfs"), "Graphs"),
    (("sort",), "Sorting"),
    (("string", "suffix", "palindrom"), "Strings"),
    (("tree",), "Advanced Data Structures"),
    (("prime", "theorem", "lemma", "divisor", "multiple", "game", "probab", "geometr"),
     "Math & Geometry"),
    (("hash",), "Arrays & Hashing"),
]

GROUP_IMPORTANCE: dict[str, float] = {name: imp for name, imp, _ in GROUPS}
GROUP_IMPORTANCE[OTHER_GROUP] = OTHER_IMPORTANCE
GROUP_ORDER: list[str] = [name for name, _, _ in GROUPS] + [OTHER_GROUP]

_TAG_TO_GROUP: dict[str, str] = {}
for _name, _imp, _tags in GROUPS:
    for _t in _tags:
        _TAG_TO_GROUP[_t] = _name


def group_for_tag(tag: str) -> str:
    """Map a LeetCode tag to its interview group."""
    if tag in _TAG_TO_GROUP:
        return _TAG_TO_GROUP[tag]
    low = tag.lower()
    for keywords, group in _KEYWORD_RULES:
        if any(k in low for k in keywords):
            return group
    return OTHER_GROUP
