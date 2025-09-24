import nltk
from nltk.corpus import wordnet as wn
import networkx as nx
import igraph as ig
import leidenalg
from tqdm import tqdm
import requests
import time
import json  
import os   


# Step 1: Load your words
try:
    with open('words.txt', 'r') as f:
        words = sorted([line.strip().lower() for line in f.readlines()])
except FileNotFoundError:
    print("Error: 'words.txt' not found. Using a sample list.")
    words = ['advocate', 'laconic', 'mitigate', 'enervate', 'bolster', 'pedestrian']

word_set = set(words)
CACHE_FILENAME = "api_cache.json"

# Step 2: Functions to get data from API and WordNet
def get_api_data_and_wordnet_relations(word):
    # This function remains the same as before
    api_defs, api_examples = [], []
    try:
        response = requests.get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}", timeout=5)
        if response.status_code == 200:
            data = response.json()[0]
            for meaning in data.get('meanings', []):
                pos = meaning.get('partOfSpeech', 'n/a')
                definition_text = next((d['definition'] for d in meaning.get('definitions', []) if d.get('definition')), None)
                example_text = next((d['example'] for d in meaning.get('definitions', []) if d.get('example')), None)
                if definition_text: 
                    api_defs.append(f"({pos}) {definition_text}")
                if example_text: 
                    api_examples.append(f"({pos}) {example_text}")
    except (requests.exceptions.RequestException, IndexError): pass

    related_words, antonyms = set(), set()
    for syn in wn.synsets(word):
        for lemma in syn.lemmas():
            related_words.add(lemma.name().lower().replace('_', ' '))
            for ant in lemma.antonyms(): antonyms.add(ant.name().lower().replace('_', ' '))
        related_synsets = syn.hypernyms() + syn.hyponyms()
        for related_syn in related_synsets:
            for lemma in related_syn.lemmas(): related_words.add(lemma.name().lower().replace('_', ' '))
    related_words.discard(word)

    return {
        'definition': "; ".join(api_defs) if api_defs else "No definition found.",
        'examples': "; ".join(api_examples) if api_examples else "No examples found.",
        'related_words': list(related_words), # Convert set to list for JSON compatibility
        'antonyms': list(antonyms) # Convert set to list for JSON compatibility
    }

# --- Caching Logic Starts Here ---
all_word_data = {}
if os.path.exists(CACHE_FILENAME):
    print(f"Loading data from cache file: {CACHE_FILENAME}")
    with open(CACHE_FILENAME, 'r') as f:
        all_word_data = json.load(f)
else:
    print("No cache file found. Fetching data from APIs (this will be slow the first time)...")
    for word in tqdm(words, desc="Phase 1: Analyzing Words"):
        all_word_data[word] = get_api_data_and_wordnet_relations(word)
        time.sleep(0.5)
    
    # Save the freshly fetched data to the cache file for next time
    with open(CACHE_FILENAME, 'w') as f:
        json.dump(all_word_data, f, indent=4)
    print(f"\nSaved new data to {CACHE_FILENAME}")
# --- Caching Logic Ends Here ---


# Step 3: Build the graph using the (now very fast) loaded data
G = nx.Graph()
print("\nBuilding graph from data...")
for word, data in tqdm(all_word_data.items(), desc="Phase 2: Building Graph"):
    G.add_node(word,
               definition=data['definition'],
               examples=data['examples'],
               related_words="; ".join(data['related_words']))
    
    # Connect to similar words
    similar_links = set(data['related_words']) & word_set
    for similar in similar_links:
        if word < similar: G.add_edge(word, similar, relation='similar', color='#1f77b4')

    # Connect to antonyms
    antonym_links = set(data['antonyms']) & word_set
    for ant in antonym_links:
        if word < ant: G.add_edge(word, ant, relation='antonym', color='#d62728')

# Step 4: Calculate Metrics and Cluster
print("\nPhase 3: Calculating metrics and clustering...")
degree = dict(G.degree())
nx.set_node_attributes(G, degree, 'degree')

similar_edges = [(u, v) for u, v, d in G.edges(data=True) if d['relation'] == 'similar']
if similar_edges:
    node_list = list(G.nodes())
    name_to_id = {name: i for i, name in enumerate(node_list)}
    id_to_name = {i: name for i, name in enumerate(node_list)}
    igraph_edges = [(name_to_id[u], name_to_id[v]) for u,v in similar_edges]
    
    igraph_graph = ig.Graph(n=len(node_list), edges=igraph_edges, directed=False)
    partition = leidenalg.find_partition(igraph_graph, leidenalg.ModularityVertexPartition)
    cluster_mapping = {id_to_name[node_id]: i for i, cluster in enumerate(partition) for node_id in cluster}
    nx.set_node_attributes(G, cluster_mapping, 'cluster')

# Step 5: Export to GraphML
output_filename = 'gre_final_study_network.graphml'
print(f"Writing final graph to {output_filename}...")
nx.write_graphml(G, output_filename)
print(f"\n✅ Success! Final network file '{output_filename}' is ready for Cytoscape.")