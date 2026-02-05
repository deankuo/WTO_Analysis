import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
from matplotlib.patches import Circle
import matplotlib.patches as mpatches
from collections import defaultdict

def visualize_network_improved(G, year, communities=None, save_fig=False):
    """
    改進的網絡視覺化，突出社群結構
    """
    if len(G.nodes()) == 0:
        print(f"No data to visualize for year {year}")
        return
    
    # 創建更大的圖形
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(20, 16))
    fig.suptitle(f"WTO Dispute Settlement Network Analysis ({year})", fontsize=16, fontweight='bold')
    
    # 如果沒有提供社群資訊，嘗試偵測
    if communities is None:
        try:
            simple_G = nx.Graph()
            for u, v, d in G.edges(data=True):
                if simple_G.has_edge(u, v):
                    simple_G[u][v]['weight'] += 1
                else:
                    simple_G.add_edge(u, v, weight=1)
            communities = list(nx.community.louvain_communities(simple_G))
        except:
            communities = [set(G.nodes())]
    
    # 準備節點顏色和位置
    node_colors, community_colors = prepare_community_colors(G.nodes(), communities)
    
    # 1. 社群導向布局（左上）
    visualize_community_layout(G, ax1, communities, node_colors, community_colors, year)
    
    # 2. 力導向布局with改進參數（右上）
    visualize_force_directed(G, ax2, node_colors, year)
    
    # 3. 圓形布局（左下）
    visualize_circular_layout(G, ax3, communities, node_colors, community_colors, year)
    
    # 4. 階層布局（右下）
    visualize_hierarchical_layout(G, ax4, communities, node_colors, community_colors, year)
    
    plt.tight_layout()
    
    if save_fig:
        plt.savefig(f'wto_network_analysis_{year}.png', dpi=300, bbox_inches='tight')
        print(f"📁 Network visualization saved as wto_network_analysis_{year}.png")
    
    plt.show()

def prepare_community_colors(nodes, communities):
    """準備社群顏色映射"""
    # 預定義的美觀顏色
    colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FECA57', 
              '#FF9FF3', '#54A0FF', '#5F27CD', '#00D2D3', '#FF9F43',
              '#C44569', '#F8B500', '#6C5CE7', '#A29BFE', '#6C7CE0']
    
    node_colors = {}
    community_colors = {}
    
    for i, community in enumerate(communities):
        color = colors[i % len(colors)]
        community_colors[i] = color
        for node in community:
            node_colors[node] = color
    
    # 未分群節點使用灰色
    for node in nodes:
        if node not in node_colors:
            node_colors[node] = '#95A5A6'
    
    return node_colors, community_colors

def visualize_community_layout(G, ax, communities, node_colors, community_colors, year):
    """社群導向布局 - 突出社群結構"""
    ax.set_title("Community-Focused Layout", fontweight='bold')
    
    # 為每個社群計算單獨的布局
    pos = {}
    community_centers = []
    
    # 計算社群中心點
    angle_step = 2 * np.pi / len(communities)
    radius = 3
    
    for i, community in enumerate(communities):
        # 社群中心
        center_x = radius * np.cos(i * angle_step)
        center_y = radius * np.sin(i * angle_step)
        community_centers.append((center_x, center_y))
        
        # 在社群內部使用圓形布局
        if len(community) == 1:
            node = list(community)[0]
            pos[node] = (center_x, center_y)
        else:
            community_list = list(community)
            inner_radius = min(0.8, len(community) * 0.15)
            
            for j, node in enumerate(community_list):
                inner_angle = j * 2 * np.pi / len(community_list)
                pos[node] = (
                    center_x + inner_radius * np.cos(inner_angle),
                    center_y + inner_radius * np.sin(inner_angle)
                )
    
    # 繪製社群背景圓圈
    for i, (center_x, center_y) in enumerate(community_centers):
        circle = Circle((center_x, center_y), 1.2, 
                       color=community_colors.get(i, '#95A5A6'), 
                       alpha=0.1, linewidth=2, fill=True)
        ax.add_patch(circle)
    
    draw_network_base(G, ax, pos, node_colors)

def visualize_force_directed(G, ax, node_colors, year):
    """改進的力導向布局"""
    ax.set_title("Force-Directed Layout (Improved)", fontweight='bold')
    
    # 使用更好的參數
    try:
        pos = nx.spring_layout(G, k=3, iterations=100, weight='weight')
    except:
        pos = nx.spring_layout(G, k=3, iterations=100)
    
    draw_network_base(G, ax, pos, node_colors)

def visualize_circular_layout(G, ax, communities, node_colors, community_colors, year):
    """圓形布局 - 按社群分組"""
    ax.set_title("Circular Layout by Community", fontweight='bold')
    
    pos = {}
    total_nodes = len(G.nodes())
    
    if len(communities) <= 1:
        # 如果只有一個社群，使用標準圓形布局
        pos = nx.circular_layout(G)
    else:
        # 按社群分段圓形布局
        angle_start = 0
        radius = 2
        
        for community in communities:
            community_list = list(community)
            angle_span = 2 * np.pi * len(community_list) / total_nodes
            
            for i, node in enumerate(community_list):
                angle = angle_start + (i * angle_span / len(community_list))
                pos[node] = (radius * np.cos(angle), radius * np.sin(angle))
            
            angle_start += angle_span
    
    draw_network_base(G, ax, pos, node_colors)

def visualize_hierarchical_layout(G, ax, communities, node_colors, community_colors, year):
    """階層布局 - 根據中心性分層"""
    ax.set_title("Hierarchical Layout by Centrality", fontweight='bold')
    
    # 計算中心性
    try:
        centrality = nx.degree_centrality(G)
    except:
        centrality = {node: 1 for node in G.nodes()}
    
    # 按中心性分層
    sorted_nodes = sorted(centrality.items(), key=lambda x: x[1], reverse=True)
    
    pos = {}
    layers = 4  # 分為4層
    nodes_per_layer = len(G.nodes()) // layers + 1
    
    for i, (node, cent) in enumerate(sorted_nodes):
        layer = i // nodes_per_layer
        position_in_layer = i % nodes_per_layer
        
        # 計算該層的角度和半徑
        radius = 0.5 + layer * 0.8
        angle = position_in_layer * 2 * np.pi / min(nodes_per_layer, len(sorted_nodes) - layer * nodes_per_layer)
        
        pos[node] = (radius * np.cos(angle), radius * np.sin(angle))
    
    draw_network_base(G, ax, pos, node_colors)

def draw_network_base(G, ax, pos, node_colors):
    """繪製網絡的基本元素"""
    
    # 計算節點大小
    try:
        degree_centrality = nx.degree_centrality(G)
        node_sizes = [degree_centrality[node] * 2000 + 200 for node in G.nodes()]
    except:
        node_sizes = [300 for _ in G.nodes()]
    
    # 準備邊的顏色和樣式
    edge_colors = []
    edge_styles = []
    edge_widths = []
    
    for u, v, d in G.edges(data=True):
        relation = d.get('relation', 'unknown')
        if relation == 'Complainant-Respondent':
            edge_colors.append('#E74C3C')  # 紅色 - 衝突
            edge_styles.append('-')
            edge_widths.append(2)
        elif relation == 'Complainant-ThirdParty':
            edge_colors.append('#27AE60')  # 綠色 - 合作
            edge_styles.append('-')
            edge_widths.append(1.5)
        elif relation == 'Respondent-ThirdParty':
            edge_colors.append('#F39C12')  # 橙色 - 複雜關係
            edge_styles.append('--')
            edge_widths.append(1)
        else:
            edge_colors.append('#95A5A6')  # 灰色 - 未知
            edge_styles.append('-')
            edge_widths.append(1)
    
    # 繪製邊
    for i, (u, v) in enumerate(G.edges()):
        x1, y1 = pos[u]
        x2, y2 = pos[v]
        ax.plot([x1, x2], [y1, y2], 
               color=edge_colors[i], 
               linestyle=edge_styles[i],
               linewidth=edge_widths[i],
               alpha=0.6)
    
    # 繪製節點
    node_colors_list = [node_colors.get(node, '#95A5A6') for node in G.nodes()]
    
    scatter = ax.scatter([pos[node][0] for node in G.nodes()],
                        [pos[node][1] for node in G.nodes()],
                        c=node_colors_list,
                        s=node_sizes,
                        alpha=0.8,
                        edgecolors='black',
                        linewidth=1)
    
    # 添加節點標籤
    for node in G.nodes():
        ax.annotate(node, pos[node], 
                   xytext=(5, 5), textcoords='offset points',
                   fontsize=8, fontweight='bold',
                   bbox=dict(boxstyle='round,pad=0.2', facecolor='white', alpha=0.7))
    
    ax.set_aspect('equal')
    ax.axis('off')

def create_network_legend():
    """創建圖例"""
    legend_elements = [
        mpatches.Patch(color='#E74C3C', label='Complainant-Respondent (Conflict)'),
        mpatches.Patch(color='#27AE60', label='Complainant-ThirdParty (Cooperation)'),
        mpatches.Patch(color='#F39C12', label='Respondent-ThirdParty (Complex)')
    ]
    return legend_elements

def visualize_network_simple_community(G, year, communities=None, save_fig=False):
    """
    簡化版本 - 只有一個突出社群的視圖
    """
    if len(G.nodes()) == 0:
        print(f"No data to visualize for year {year}")
        return
    
    plt.figure(figsize=(14, 10))
    
    # 如果沒有社群資訊，嘗試偵測
    if communities is None:
        try:
            simple_G = nx.Graph()
            for u, v, d in G.edges(data=True):
                if simple_G.has_edge(u, v):
                    simple_G[u][v]['weight'] += 1
                else:
                    simple_G.add_edge(u, v, weight=1)
            communities = list(nx.community.louvain_communities(simple_G))
        except:
            communities = [set(G.nodes())]
    
    # 準備顏色
    node_colors, community_colors = prepare_community_colors(G.nodes(), communities)
    
    # 社群導向布局
    pos = {}
    angle_step = 2 * np.pi / len(communities)
    radius = 4
    
    for i, community in enumerate(communities):
        center_x = radius * np.cos(i * angle_step)
        center_y = radius * np.sin(i * angle_step)
        
        if len(community) == 1:
            node = list(community)[0]
            pos[node] = (center_x, center_y)
        else:
            community_list = list(community)
            inner_radius = min(1.2, len(community) * 0.2)
            
            for j, node in enumerate(community_list):
                inner_angle = j * 2 * np.pi / len(community_list)
                pos[node] = (
                    center_x + inner_radius * np.cos(inner_angle),
                    center_y + inner_radius * np.sin(inner_angle)
                )
    
    # 繪製社群背景
    for i, community in enumerate(communities):
        if len(community) > 1:
            center_x = radius * np.cos(i * angle_step)
            center_y = radius * np.sin(i * angle_step)
            circle = Circle((center_x, center_y), 1.8, 
                           color=community_colors.get(i, '#95A5A6'), 
                           alpha=0.15, linewidth=2, fill=True)
            plt.gca().add_patch(circle)
    
    # 繪製網絡
    draw_network_base(G, plt.gca(), pos, node_colors)
    
    # 添加圖例
    legend_elements = create_network_legend()
    plt.legend(handles=legend_elements, loc='upper right', bbox_to_anchor=(1, 1))
    
    plt.title(f"WTO Dispute Settlement Network - Community Structure ({year})", 
              fontsize=14, fontweight='bold', pad=20)
    
    if save_fig:
        plt.savefig(f'wto_network_community_{year}.png', dpi=300, bbox_inches='tight')
        print(f"📁 Community network saved as wto_network_community_{year}.png")
    
    plt.show()