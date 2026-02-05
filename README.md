# WTO Dispute Settlement Network Analysis

## 📋 Project Overview

This project analyzes World Trade Organization (WTO) dispute settlement cases through network analysis and relationship modeling. We examine the complex relationships between complainant countries, respondent countries, and third-party participants to understand patterns in international trade disputes.

**Project Start Date:** 
**Data Source:** [WTO Dispute Settlement](https://www.wto.org/english/tratop_e/dispu_e/dispu_e.htm)

## 🎯 Research Objectives

1. **Network Relationship Analysis**: Map and analyze relationships between countries in WTO dispute cases
2. **Conflict Pattern Identification**: Identify patterns in trade conflicts and cooperation
3. **Third-Party Behavior Study**: Understand how third-party countries position themselves in disputes
4. **Temporal Analysis**: Track how relationships evolve over time
5. **Predictive Modeling**: Develop models to predict dispute outcomes and third-party alignment

## 📊 Dataset Structure

### Core Features

| Feature Name | Type | Description | Example Values |
|--------------|------|-------------|----------------|
| **Title (Dispute)** | string | Official case title | "EC --- Selected Customs Matters" |
| **Current Status** | category | Current stage of dispute resolution | "Report(s) adopted", "Panel report under appeal" |
| **Complainant** | agent (country) | Country filing the complaint | United States, Canada |
| **Respondent** | agent (country) | Country being complained against | European Communities, Australia |
| **Third Parties** | agents (countries) | Countries participating as third parties | Multiple countries listed |

### Key Dates and Timeline Features

- **Consultations Requested**: Initial consultation date
- **Panel Requested**: Date panel establishment was requested
- **Panel Established**: Date panel was officially established
- **Panel Report Circulated**: Date panel report was published
- **Appellate Body Report**: Date of appellate decision (if applicable)

### Legal Framework Features

- **Agreements Cited (Consultation)**: Legal articles cited in consultation request
- **Agreements Cited (Panel)**: Legal articles cited in panel request
- **Mutually Agreed Solution**: Whether parties reached agreement outside formal process

## 🏗️ Project Structure

```
wto-dispute-analysis/
├── README.md                   # This file
├── data/
│   ├── raw/                    # Scrapped data 
│       └── wto_cases.csv       # Source data file
│   ├── processed/              # Cleaned and engineered                               
features
├── src/
│   ├── WTO.ipynb               # Web Scrapping
│   ├── network_analysis.py     # Network metrics calculation
│   ├── sentiment_analysis.py   # Text analysis of legal documents
│   ├── temporal_analysis.py    # Time-series analysis
│   └── data_processing.py      # Data cleaning and feature engineering
├── analysis/
│   ├── exploratory/            # Exploratory data analysis notebooks
│   ├── temporal_analysis.py    # Network analysis results
│   └── reports/                # Analysis reports and findings
├── visualization/
│   ├── network_viz.py         # Network visualization tools
│   ├── dashboard.py           # Interactive dashboard
│   └── plots/                 # Generated visualizations
├── models/
│   ├── prediction_models.py   # Outcome prediction models
│   └── trained_models/        # Saved model files
├── tests/
│   └── test_*.py              # Unit tests
├── docs/
│   ├── methodology.md         # Detailed methodology
│   ├── notes.md               # Notes of issues and questions
│   ├── case_studies.md        # Detailed case analysis
│   └── api_documentation.md   # Code documentation
├── requirements.txt           # Python dependencies
└── config.yaml               # Configuration settings
```

## 🔬 Methodology

### Network Construction

1. **Node Creation**: Each country becomes a node in the network
2. **Edge Creation**: Relationships based on dispute roles:
   - Direct edges between complainants and respondents
   - Indirect edges through third-party participation
3. **Edge Weighting**: Based on multiple factors:
   - Frequency of interaction
   - Outcome favorability
   - Legal citation complexity

### Analytical Approaches

#### 1. Index
- Nodes
- Edges (Compliant-Respondent; Compliant-Third Parties; Third Parties-Respondent)
- Conflict Density; Support Ratio (equals to 1)
- balanced / unbalanced triangle (weighting should be 1 of each edge)
- Community (Currently using Louvain algorithm)
   - Group members
   - Internal relations
   - Type (Cooperate / Conflict / Mixed)
   - Modified Modularity (Currently considering positive & negative relations) / Modularity
   - Clustering
   - Centrality
   - Betweenness
   - Positive Degree
   - Negative Degree

#### 2. Text Processing
   - WTO DSB Web Scrapping
   - Landing AI parse the best
   - What to include and what to exclude? (Report?)
   - How to measure the intensity between countries?
   - RAG + LLM?

#### 3. RAG
   - Dense retrieval 
   - Adaptive RAG

#### 3. Structural Analysis
- **Balance Theory**: Analyzing balanced vs. unbalanced triads
- **Community Detection**: Identifying country clusters/alliances
- **Centrality Analysis**: Identifying key players in dispute network

#### 4. Temporal Analysis
- **Longitudinal Networks**: Year-by-year network evolution
- **Relationship Persistence**: How long relationships last
- **Conflict Escalation Patterns**: Paths from consultation to retaliation

#### 5. Text Analysis
- **Sentiment Analysis**: Emotional tone in legal submissions
- **Legal Citation Analysis**: Complexity and types of laws cited
- **Argument Similarity**: Comparing third-party positions

## 📈 Key Research Questions

### Primary Questions
1. **What factors predict third-party alignment in WTO disputes?**
2. **How do bilateral trade relationships influence dispute outcomes?**
3. **Can we predict case escalation from consultation to panel stage?**
4. **What network positions make countries more likely to be involved in disputes?**

### Secondary Questions
1. How has the dispute settlement system evolved since WTO establishment?
2. Are there persistent "coalition" patterns among countries?
3. What role do regional trade agreements play in dispute patterns?
4. How do different legal areas (anti-dumping, SPS, etc.) show different network patterns?

## 🛠️ Technical Implementation

### Core Technologies
- **Python 3.8+**: Primary programming language
- **NetworkX**: Network analysis and graph theory
- **Pandas**: Data manipulation and analysis
- **Scikit-learn**: Machine learning models
- **Plotly/Dash**: Interactive visualizations
- **NLTK/spaCy**: Natural language processing

### Key Network Analysis Functions

```python
# Core analytical functions from src/network_analysis.py
calculate_conflict_metrics(G, edge_count)    # Overall network conflict measures
calculate_triangle_metrics(G)               # Balanced/unbalanced relationship triads
calculate_modularity(G)                     # Community structure strength
calculate_centrality_metrics(G)             # Node importance measures
```

## 📋 Sample Cases

### DS315: European Communities - Selected Customs Matters
- **Complainant**: United States
- **Respondent**: European Communities  
- **Status**: Report(s) adopted, with recommendation to bring measure(s) into conformity
- **Third Parties**: 9 countries (Argentina, Australia, Brazil, China, Chinese Taipei, Hong Kong China, India, Japan, Korea)

### DS18: Australia - Measures Affecting Importation of Salmon
- **Complainant**: Canada
- **Respondent**: Australia
- **Status**: Mutually agreed solution notified
- **Third Parties**: 4 countries (European Communities, India, Norway, United States)

### DS539: US - Anti-Dumping and Countervailing Duties (Korea)
- **Complainant**: Korea, Republic of
- **Respondent**: United States
- **Status**: Panel report under appeal
- **Third Parties**: 8 countries (Brazil, Canada, China, Egypt, European Union, India, Japan, Kazakhstan, Mexico, Norway, Russian Federation)

## 🚀 Getting Started