import networkx as nx
import json
from collections import defaultdict
import numpy as np


def calculate_conflict_metrics(G, edge_count):
    """
    Calculate various conflict-related metrics for the network
    
    Parameters:
    G (nx.MultiGraph): Network graph
    edge_count (dict): Dictionary containing edge counts by type and pair of countries
    """
    
    # Total number of edges of each type
    edge_types = defaultdict(int)
    for edge in G.edges(data=True):
        # Each edge is a tuple (source, target, attributes) ex: ('CountryA', 'CountryB', {'relation': 'Complainant-Respondent'})
        edge_types[edge[2]['relation']] += 1
    
    # Total number of edges (The second equation should be the total number we want to consider as we are not considering the network density)
    #total_possible_edges = len(G.nodes()) * (len(G.nodes()) - 1) / 2
    total_relationships = sum(edge_types.values())
    
    # Calculate conflict density
    # 衝突指的是案件當中直接對質的雙邊關係
    # 應該要考慮一下third party - Respondent的關係權重
    conflict_density = (edge_types['Complainant-Respondent'] + edge_types['Respondent-ThirdParty']) / total_relationships if total_relationships > 0 else 0
    
    # Calculate support ratio
    # 支持指的是第三國與申訴國的關係，因為這兩個角色的訴求相同，應該會有相似的利害關係
    support_ratio = edge_types['Complainant-ThirdParty'] / total_relationships if total_relationships > 0 else 0
    
    # Calculate triangle metrics
    triangles = calculate_triangle_metrics(G)
    
    # Calculate modularity-based metrics
    modularity = calculate_modularity(G)
    
    # Calculate centrality metrics
    centrality_metrics = calculate_centrality_metrics(G)
    
    return {
        'edge_counts': dict(edge_types),
        'conflict_density': conflict_density,
        'support_ratio': support_ratio,
        'triangle_metrics': triangles,
        'modularity': modularity,
        'centrality': centrality_metrics
    }

def calculate_triangle_metrics(G):
    """
    Calculate balanced and unbalanced triangles in the network.
    根據平衡三角理論的計算，這邊不需要考慮方向性的問題，因為我們只關心三個節點之間的關係是否平衡。
    """
    triangles = {
        'balanced': 0,
        'unbalanced': 0
    }
    
    # Get all possible triangles
    for node1 in G.nodes():
        for node2 in G.nodes():
            for node3 in G.nodes():
                if node1 < node2 < node3:  # Avoid counting same triangle multiple times
                    edges = []
                    if G.has_edge(node1, node2):
                        edges.append(G[node1][node2][0]['relation'])
                    if G.has_edge(node2, node3):
                        edges.append(G[node2][node3][0]['relation'])
                    if G.has_edge(node1, node3):
                        edges.append(G[node1][node3][0]['relation'])
                    
                    if len(edges) == 3:  # Complete triangle
                        # Define balance based on relationship types
                        conflict_count = edges.count('Complainant-Respondent') + edges.count('Respondent-ThirdParty') # 衝突包含申訴國與被申訴國，以及被申訴國與第三國
                        if conflict_count % 2 == 0:  # Even number of negative relationships
                            triangles['balanced'] += 1
                        else:
                            triangles['unbalanced'] += 1
    
    return triangles

def calculate_modularity(G):
    """
    Calculate modularity for WTO network considering both positive and negative relationships
    
    Parameters:
    G (nx.MultiGraph): Network with both positive and negative edges
        - 'Complainant-Respondent' or 'Respondent-ThirdParty': negative relationship
        - 'Complainant-ThirdParty': positive relationship
    
    Returns:
    dict: Various modularity-related metrics
    """
    # Step 1: Separate positive and negative networks with weights
    # 為什麼不使用nx.community.modularity()直接計算呢？因為我們需要考慮正負關係的權重。
    # Step 1: 建立互動強度網絡
    interaction_G = nx.Graph()
    edge_interactions = defaultdict(lambda: {
        'total': 0,
        'positive': 0, 
        'negative': 0,
        'types': []
    })
    
    # 統計所有互動（不論正負）
    for edge in G.edges(data=True):
        source, target = edge[0], edge[1]
        relation = edge[2]['relation']
        
        # 統計總互動次數
        edge_interactions[(source, target)]['total'] += 1
        edge_interactions[(source, target)]['types'].append(relation)
        
        # 分類正負關係
        if relation in ['Complainant-Respondent', 'Respondent-ThirdParty']:
            edge_interactions[(source, target)]['negative'] += 1
        elif relation == 'Complainant-ThirdParty':
            edge_interactions[(source, target)]['positive'] += 1
    
    # 建立基於總互動強度的網絡
    for (source, target), interactions in edge_interactions.items():
        weight = interactions['total']  # 使用總互動次數作為權重
        interaction_G.add_edge(source, target, weight=weight)
    
    # Step 2: 基於互動強度進行社群偵測
    try:
        communities = nx.community.louvain_communities(interaction_G, weight='weight')
    except:
        # 如果偵測失敗，將所有節點視為一個社群
        communities = [set(interaction_G.nodes())]
    
    # Step 3: 分析各社群內部關係模式
    community_analysis = {}
    
    for i, community in enumerate(communities):
        # 統計社群內部的關係
        internal_positive = 0
        internal_negative = 0
        
        community_list = list(community)
        for j in range(len(community_list)):
            for k in range(j + 1, len(community_list)):
                pair = (community_list[j], community_list[k])
                reverse_pair = (community_list[k], community_list[j])
                
                # 檢查這對國家是否有互動
                if pair in edge_interactions:
                    interactions = edge_interactions[pair]
                elif reverse_pair in edge_interactions:
                    interactions = edge_interactions[reverse_pair]
                else:
                    continue
                
                internal_positive += interactions['positive']
                internal_negative += interactions['negative']
        
        total_internal = internal_positive + internal_negative
        
        if total_internal > 0:
            cooperation_ratio = internal_positive / total_internal
            conflict_ratio = internal_negative / total_internal
            
            # 判斷社群特性
            if cooperation_ratio > 0.7:
                community_type = "cooperation_dominant"
            elif conflict_ratio > 0.7:
                community_type = "conflict_dominant"
            else:
                community_type = "mixed"
        else:
            cooperation_ratio = 0
            conflict_ratio = 0
            community_type = "isolated"
        
        community_analysis[i] = {
            'members': list(community),
            'size': len(community),
            'internal_positive': internal_positive,
            'internal_negative': internal_negative,
            'cooperation_ratio': cooperation_ratio,
            'conflict_ratio': conflict_ratio,
            'type': community_type
        }
    
    # Step 4: 分析社群間關係
    inter_community_relations = {}
    communities_list = list(communities)
    
    for i in range(len(communities_list)):
        for j in range(i + 1, len(communities_list)):
            
            between_positive = 0
            between_negative = 0
            
            # 計算兩個社群間的關係
            for member_i in communities_list[i]:
                for member_j in communities_list[j]:
                    pair1 = (member_i, member_j)
                    pair2 = (member_j, member_i)
                    
                    if pair1 in edge_interactions:
                        interactions = edge_interactions[pair1]
                    elif pair2 in edge_interactions:
                        interactions = edge_interactions[pair2]
                    else:
                        continue
                    
                    between_positive += interactions['positive']
                    between_negative += interactions['negative']
            
            total_between = between_positive + between_negative
            
            if total_between > 0:
                tension = between_negative / total_between
                inter_community_relations[(i, j)] = {
                    'positive': between_positive,
                    'negative': between_negative,
                    'tension': tension
                }
    
    # Step 5: 計算整體指標
    total_positive = sum(interactions['positive'] for interactions in edge_interactions.values())
    total_negative = sum(interactions['negative'] for interactions in edge_interactions.values())
    total_relations = total_positive + total_negative
    
    # 計算網絡的集群係數
    try:
        clustering = nx.average_clustering(interaction_G, weight='weight')
    except:
        clustering = 0
    
    # 計算修正模組性（基於社群內部關係品質）
    modified_modularity = 0
    for analysis in community_analysis.values():
        if analysis['internal_positive'] + analysis['internal_negative'] > 0:
            # 社群品質 = (內部合作 - 內部衝突) / 總關係數
            community_quality = (analysis['internal_positive'] - analysis['internal_negative']) / total_relations
            modified_modularity += community_quality
    
    return {
        'communities': [list(c) for c in communities],
        'community_count': len(communities),
        'community_analysis': community_analysis,
        'inter_community_relations': inter_community_relations,
        'modified_modularity': modified_modularity,
        'clustering': clustering,
        'global_cooperation_ratio': total_positive / total_relations if total_relations > 0 else 0,
        'global_stats': {
            'total_positive': total_positive,
            'total_negative': total_negative,
            'total_relations': total_relations
        }
    }

def calculate_centrality_metrics(G):
    """Calculate various centrality metrics"""
    return {
        'degree': nx.degree_centrality(G),
        'betweenness': nx.betweenness_centrality(G),
        'eigenvector': nx.eigenvector_centrality_numpy(G),
        'positive_degree': calculate_positive_degree_centrality(G),
        'negative_degree': calculate_negative_degree_centrality(G)
    }

def calculate_positive_degree_centrality(G):
    """Calculate degree centrality considering only positive relationships"""
    pos_centrality = {}
    for node in G.nodes():
        positive_edges = sum(1 for edge in G.edges(node, data=True) 
                           if edge[2]['relation'] in ['Complainant-ThirdParty', 'Respondent-ThirdParty'])
        pos_centrality[node] = positive_edges / (len(G.nodes()) - 1)
    return pos_centrality

def calculate_negative_degree_centrality(G):
    """Calculate degree centrality considering only negative relationships"""
    neg_centrality = {}
    for node in G.nodes():
        negative_edges = sum(1 for edge in G.edges(node, data=True) 
                           if edge[2]['relation'] == 'Complainant-Respondent')
        neg_centrality[node] = negative_edges / (len(G.nodes()) - 1)
    return neg_centrality

## Simple Modularity Calculation (Not recommended)
def simple_modularity(G):
    """
    Calculate a simple modularity score for the network.
    
    Parameters:
    G (nx.MultiGraph): Network graph
    
    Returns:
    float: Simple modularity score
    """
    # 首先需要建立簡化的網絡（去除多重邊）
    simple_G = nx.Graph()
    edge_weights = defaultdict(int)
    
    # 統計邊的權重
    for edge in G.edges(data=True):
        source, target = edge[0], edge[1]
        edge_weights[(source, target)] += 1
    
    # 建立簡化網絡
    for (source, target), weight in edge_weights.items():
        simple_G.add_edge(source, target, weight=weight)
    
    # 進行社群偵測
    try:
        communities_nx = nx.community.louvain_communities(simple_G, weight='weight')
        
        # 計算標準 modularity
        standard_modularity = nx.community.modularity(simple_G, communities_nx, weight='weight')
        
        print(f"標準 Modularity: {standard_modularity:.3f}")
        print(f"偵測到的社群數: {len(communities_nx)}")
        
        for i, community in enumerate(communities_nx):
            print(f"社群 {i}: {list(community)}")
            
    except Exception as e:
        print(f"標準方法失敗: {e}")
        standard_modularity = 0
        communities_nx = []
        
    return standard_modularity, communities_nx