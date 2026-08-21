from __future__ import annotations

import networkx as nx

CRITICAL_NODES = {'myocardial_infarction', 'sepsis', 'stroke', 'respiratory_failure', 'internal_bleeding'}


def build_symptom_graph() -> nx.Graph:
    graph = nx.Graph()
    edges = [
        ('chest_pain', 'cardiac_risk'), ('jaw_pain', 'cardiac_risk'), ('nausea', 'cardiac_risk'),
        ('cardiac_risk', 'myocardial_infarction'), ('fever', 'infection_risk'), ('lethargy', 'infection_risk'),
        ('poor_feeding', 'infection_risk'), ('confusion', 'infection_risk'), ('infection_risk', 'sepsis'),
        ('confusion', 'neurological_risk'), ('weakness', 'neurological_risk'), ('speech_change', 'neurological_risk'),
        ('neurological_risk', 'stroke'), ('shortness_of_breath', 'respiratory_risk'), ('low_spo2', 'respiratory_risk'),
        ('respiratory_risk', 'respiratory_failure'), ('trauma', 'bleeding_risk'), ('deformity', 'trauma'),
        ('abdominal_pain', 'bleeding_risk'), ('bleeding_risk', 'internal_bleeding'), ('tachycardia', 'shock_risk'),
        ('low_bp', 'shock_risk'), ('shock_risk', 'internal_bleeding'), ('shock_risk', 'sepsis'),
        ('ankle_pain', 'musculoskeletal'), ('musculoskeletal', 'minor_injury'), ('headache', 'neurological_risk'),
        ('vomiting', 'infection_risk'), ('dizziness', 'cardiac_risk'), ('rash', 'infection_risk'),
        ('cough', 'respiratory_risk'), ('wheeze', 'respiratory_risk'), ('back_pain', 'bleeding_risk'),
        ('fainting', 'cardiac_risk'), ('pregnancy', 'bleeding_risk'), ('burn', 'trauma'),
    ]
    graph.add_edges_from((a, b, {'weight': 0.5}) for a, b in edges)
    for node in graph.nodes:
        graph.nodes[node]['kind'] = 'critical' if node in CRITICAL_NODES else ('hub' if node.endswith('_risk') else 'symptom')
    return graph


def synaptic_update(graph: nx.Graph, source_node: str, target_node: str, override_delta: int, learning_rate: float = .15) -> tuple[float, float]:
    if not graph.has_edge(source_node, target_node):
        return .5, .5
    old = graph[source_node][target_node].get('weight', .5)
    new = min(1.0, max(0.0, old + learning_rate * override_delta))
    graph[source_node][target_node]['weight'] = new
    return old, new
