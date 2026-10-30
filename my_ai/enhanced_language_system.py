#!/usr/bin/env python3
"""Enhanced language and mesh system for improved understanding and context."""

from __future__ import annotations

import re
import json
import math
import difflib
from collections import defaultdict, deque
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Set, Any
from dataclasses import dataclass, field
import networkx as nx

@dataclass
class LanguageConcept:
    """Represents a concept or entity in the language system."""
    id: str
    name: str
    description: str = ""
    category: str = "General"
    aliases: Set[str] = field(default_factory=set)
    related_concepts: Set[str] = field(default_factory=set)
    context_patterns: List[str] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)
    strength: float = 1.0  # Confidence in this concept
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

@dataclass
class LanguageRelation:
    """Represents a relationship between concepts."""
    source: str
    target: str
    relation_type: str  # e.g., "is_a", "part_of", "causes", "used_for"
    strength: float = 1.0
    context: str = ""
    examples: List[str] = field(default_factory=list)
    bidirectional: bool = False
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

class EnhancedLanguageSystem:
    """Advanced language understanding system with mesh relationships."""

    def __init__(self):
        """Initialize the language system."""
        self.concepts: Dict[str, LanguageConcept] = {}
        self.relations: List[LanguageRelation] = []
        self.graph = nx.DiGraph()  # NetworkX graph for relationship visualization
        self.category_hierarchy = {}  # Hierarchical organization of categories
        self.context_window = 5  # Number of surrounding words to consider for context
        self.min_relation_strength = 0.3  # Minimum strength to consider a relation
        self._initialize_default_concepts()

    def _initialize_default_concepts(self):
        """Initialize with default concepts and relationships."""
        # Add core programming concepts
        core_concepts = [
            ("programming", "Programming", "The process of creating computer programs"),
            ("code", "Code", "Instructions written in a programming language"),
            ("function", "Function", "Reusable block of code that performs a specific task"),
            ("variable", "Variable", "Container for storing data values"),
            ("loop", "Loop", "Programming construct that repeats a block of code"),
            ("condition", "Condition", "Expression that evaluates to true or false"),
            ("class", "Class", "Blueprint for creating objects with specific properties and methods"),
            ("object", "Object", "Instance of a class with specific data and behavior"),
            ("algorithm", "Algorithm", "Step-by-step procedure for solving a problem"),
            ("data_structure", "Data Structure", "Particular way of organizing and storing data"),
        ]

        for id, name, desc in core_concepts:
            self.add_concept(id, name, desc, category="Programming")

        # Add relationships between core concepts
        self.add_relation("programming", "code", "creates")
        self.add_relation("code", "function", "contains")
        self.add_relation("code", "variable", "contains")
        self.add_relation("code", "loop", "contains")
        self.add_relation("code", "condition", "contains")
        self.add_relation("programming", "algorithm", "uses")
        self.add_relation("programming", "data_structure", "uses")
        self.add_relation("class", "object", "instantiates")
        self.add_relation("object", "variable", "contains")
        self.add_relation("object", "function", "contains")

        # Add language-related concepts
        language_concepts = [
            ("syntax", "Syntax", "Rules that define the structure of a language"),
            ("semantics", "Semantics", "Meaning of language constructs"),
            ("compiler", "Compiler", "Program that translates source code to machine code"),
            ("interpreter", "Interpreter", "Program that executes code directly"),
            ("debugging", "Debugging", "Process of finding and fixing errors in code"),
            ("testing", "Testing", "Process of verifying that code works as expected"),
        ]

        for id, name, desc in language_concepts:
            self.add_concept(id, name, desc, category="Programming/Language")

        # Add relationships for language concepts
        self.add_relation("code", "syntax", "follows")
        self.add_relation("code", "semantics", "has")
        self.add_relation("compiler", "code", "translates")
        self.add_relation("interpreter", "code", "executes")
        self.add_relation("programming", "debugging", "requires")
        self.add_relation("programming", "testing", "requires")

        # Initialize category hierarchy
        self._update_category_hierarchy()

    def add_concept(self, id: str, name: str, description: str = "", 
                  category: str = "General", aliases: Optional[List[str]] = None) -> LanguageConcept:
        """Add a new concept to the language system."""
        concept = LanguageConcept(
            id=id,
            name=name,
            description=description,
            category=category,
            aliases=set(aliases or [])
        )
        self.concepts[id] = concept

        # Add to graph
        self.graph.add_node(id, **{
            "name": name,
            "description": description,
            "category": category,
            "aliases": list(concept.aliases),
            "strength": concept.strength
        })

        # Update category hierarchy
        self._update_category_hierarchy()

        return concept

    def update_concept(self, id: str, **kwargs) -> Optional[LanguageConcept]:
        """Update an existing concept."""
        if id not in self.concepts:
            return None

        concept = self.concepts[id]
        for key, value in kwargs.items():
            if hasattr(concept, key):
                setattr(concept, key, value)
            concept.updated_at = datetime.now()

        # Update graph
        for key, value in kwargs.items():
            if key in ["name", "description", "category", "aliases", "strength"]:
                self.graph.nodes[id][key] = value

        return concept

    def add_relation(self, source: str, target: str, relation_type: str, 
                    strength: float = 1.0, context: str = "", 
                    bidirectional: bool = False) -> Optional[LanguageRelation]:
        """Add a relation between two concepts."""
        if source not in self.concepts or target not in self.concepts:
            return None

        relation = LanguageRelation(
            source=source,
            target=target,
            relation_type=relation_type,
            strength=strength,
            context=context,
            bidirectional=bidirectional
        )
        self.relations.append(relation)

        # Add to graph
        self.graph.add_edge(source, target, 
                           relation_type=relation_type,
                           strength=strength,
                           context=context,
                           bidirectional=bidirectional)

        # If bidirectional, add reverse relation
        if bidirectional:
            reverse_relation = LanguageRelation(
                source=target,
                target=source,
                relation_type=relation_type,
                strength=strength,
                context=context,
                bidirectional=True
            )
            self.relations.append(reverse_relation)
            self.graph.add_edge(target, source,
                               relation_type=relation_type,
                               strength=strength,
                               context=context,
                               bidirectional=True)

        return relation

    def find_concepts(self, query: str, max_results: int = 10) -> List[Tuple[str, float]]:
        """Find concepts related to the query."""
        query = query.lower()
        results = []

        # Direct name or alias match
        for id, concept in self.concepts.items():
            if query == concept.name.lower() or query in [a.lower() for a in concept.aliases]:
                results.append((id, 1.0))

        # Partial name match
        if not results:
            for id, concept in self.concepts.items():
                if query in concept.name.lower():
                    results.append((id, 0.8))

        # Concept description match
        if not results:
            for id, concept in self.concepts.items():
                if query in concept.description.lower():
                    results.append((id, 0.6))

        # Related concepts via graph
        if not results:
            # Use graph traversal to find related concepts
            for id, concept in self.concepts.items():
                # Check if any related concepts match the query
                related = self.graph.neighbors(id)
                for rel_id in related:
                    rel_concept = self.concepts.get(rel_id)
                    if rel_concept and query in rel_concept.name.lower():
                        # Calculate score based on relation strength and concept relevance
                        strength = self.graph[id][rel_id].get("strength", 0.5)
                        results.append((id, strength * 0.7))

        # Fuzzy match
        if not results:
            names = [c.name.lower() for c in self.concepts.values()]
            matches = difflib.get_close_matches(query, names, n=max_results, cutoff=0.6)
            for match in matches:
                for id, concept in self.concepts.items():
                    if concept.name.lower() == match:
                        results.append((id, 0.5))

        # Sort by score and return top results
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:max_results]

    def find_related_concepts(self, concept_id: str, relation_types: Optional[List[str]] = None,
                             max_depth: int = 2, max_results: int = 10) -> List[Tuple[str, float, List[str]]]:
        """Find concepts related to the given concept ID."""
        if concept_id not in self.concepts:
            return []

        results = []
        visited = set()

        # BFS to find related concepts
        queue = deque([(concept_id, 1.0, [])])  # (concept_id, strength, path)

        while queue:
            current_id, strength, path = queue.popleft()

            if current_id in visited or strength < self.min_relation_strength:
                continue

            visited.add(current_id)

            # Get neighbors
            neighbors = self.graph.neighbors(current_id)

            for neighbor_id in neighbors:
                edge_data = self.graph[current_id][neighbor_id]
                relation_type = edge_data.get("relation_type", "related")

                # Filter by relation type if specified
                if relation_types and relation_type not in relation_types:
                    continue
                    
                # Calculate new strength
                new_strength = strength * edge_data.get("strength", 0.7)
                
                # Create new path
                new_path = path + [f"{current_id} -> {neighbor_id} ({relation_type})"]
                
                # Add to results if not already included
                if len(new_path) <= max_depth:
                    results.append((neighbor_id, new_strength, new_path))
                    
                # Add to queue for further exploration
                    queue.append((neighbor_id, new_strength, new_path))

                # Calculate new strength
                edge_strength = edge_data.get("strength", 1.0)
                new_strength = strength * edge_strength

                # Add to results if not the original concept
                if neighbor_id != concept_id:
                    results.append((neighbor_id, new_strength, path + [current_id]))

                # Add to queue if we haven't reached max depth
                if len(path) < max_depth:
                    queue.append((neighbor_id, new_strength, path + [current_id]))

        # Sort by strength and return top results
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:max_results]

    def extract_concepts_from_text(self, text: str) -> List[Tuple[str, float]]:
        """Extract concepts from text and return them with relevance scores."""
        # Simple tokenization - could be enhanced with NLP
        words = re.findall(r'\b\w+\b', text.lower())

        # Count concept occurrences
        concept_counts = defaultdict(int)

        for word in words:
            # Find matching concepts
            matches = self.find_concepts(word, max_results=5)
            for concept_id, score in matches:
                concept_counts[concept_id] += score

        # Normalize counts
        if concept_counts:
            max_count = max(concept_counts.values())
            normalized_counts = {k: v/max_count for k, v in concept_counts.items()}
        else:
            normalized_counts = {}

        return list(normalized_counts.items())

    def _update_category_hierarchy(self):
        """Update the category hierarchy based on current concepts."""
        categories = defaultdict(set)

        # Collect all categories
        for concept in self.concepts.values():
            categories[concept.category].add(concept.id)

        # Build hierarchy
        self.category_hierarchy = {}
        for category, concept_ids in categories.items():
            if "/" in category:
                # Hierarchical category
                parts = category.split("/")
                current_level = self.category_hierarchy

                for i, part in enumerate(parts):
                    if part not in current_level:
                        current_level[part] = {}
                    current_level = current_level[part]
            else:
                # Top-level category
                self.category_hierarchy[category] = list(concept_ids)

    def get_concept_by_id(self, concept_id: str) -> Optional[LanguageConcept]:
        """Get a concept by its ID."""
        return self.concepts.get(concept_id)

    def get_concepts_by_category(self, category: str, recursive: bool = True) -> List[LanguageConcept]:
        """Get all concepts in a category."""
        concepts = []

        for concept in self.concepts.values():
            if concept.category == category:
                concepts.append(concept)
            elif recursive and category in concept.category:
                concepts.append(concept)

        return concepts

    def get_category_hierarchy(self) -> Dict:
        """Get the category hierarchy."""
        return self.category_hierarchy

    def strengthen_relation(self, source: str, target: str, amount: float = 0.1):
        """Strengthen the relation between two concepts."""
        for i, relation in enumerate(self.relations):
            if relation.source == source and relation.target == target:
                self.relations[i].strength = min(1.0, relation.strength + amount)
                self.relations[i].updated_at = datetime.now()

                # Update graph
                if self.graph.has_edge(source, target):
                    self.graph[source][target]["strength"] = self.relations[i].strength

                # If bidirectional, update reverse relation too
                if relation.bidirectional:
                    for j, rel in enumerate(self.relations):
                        if rel.source == target and rel.target == source:
                            self.relations[j].strength = min(1.0, rel.strength + amount)
                            self.relations[j].updated_at = datetime.now()

                            if self.graph.has_edge(target, source):
                                self.graph[target][source]["strength"] = self.relations[j].strength

                break

    def add_context_pattern(self, concept_id: str, pattern: str):
        """Add a context pattern for a concept."""
        if concept_id in self.concepts:
            self.concepts[concept_id].context_patterns.append(pattern)
            self.concepts[concept_id].updated_at = datetime.now

    def add_example(self, concept_id: str, example: str):
        """Add an example for a concept."""
        if concept_id in self.concepts:
            self.concepts[concept_id].examples.append(example)
            self.concepts[concept_id].updated_at = datetime.now

    def save_to_json(self, filepath: str):
        """Save the language system to a JSON file."""
        data = {
            "concepts": [
                {
                    "id": c.id,
                    "name": c.name,
                    "description": c.description,
                    "category": c.category,
                    "aliases": list(c.aliases),
                    "related_concepts": list(c.related_concepts),
                    "context_patterns": c.context_patterns,
                    "examples": c.examples,
                    "strength": c.strength,
                    "created_at": c.created_at.isoformat(),
                    "updated_at": c.updated_at.isoformat()
                }
                for c in self.concepts.values()
            ],
            "relations": [
                {
                    "source": r.source,
                    "target": r.target,
                    "relation_type": r.relation_type,
                    "strength": r.strength,
                    "context": r.context,
                    "examples": r.examples,
                    "bidirectional": r.bidirectional,
                    "created_at": r.created_at.isoformat(),
                    "updated_at": r.updated_at.isoformat()
                }
                for r in self.relations
            ]
        }

        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load_from_json(cls, filepath: str) -> EnhancedLanguageSystem:
        """Load a language system from a JSON file."""
        with open(filepath, 'r') as f:
            data = json.load(f)

        system = cls()

        # Load concepts
        for concept_data in data["concepts"]:
            concept = LanguageConcept(
                id=concept_data["id"],
                name=concept_data["name"],
                description=concept_data["description"],
                category=concept_data["category"],
                aliases=set(concept_data.get("aliases", [])),
                related_concepts=set(concept_data.get("related_concepts", [])),
                context_patterns=concept_data.get("context_patterns", []),
                examples=concept_data.get("examples", []),
                strength=concept_data.get("strength", 1.0),
                created_at=datetime.fromisoformat(concept_data["created_at"]),
                updated_at=datetime.fromisoformat(concept_data["updated_at"])
            )
            system.concepts[concept.id] = concept

            # Add to graph
            system.graph.add_node(concept.id, **{
                "name": concept.name,
                "description": concept.description,
                "category": concept.category,
                "aliases": list(concept.aliases),
                "strength": concept.strength
            })

        # Load relations
        for rel_data in data["relations"]:
            relation = LanguageRelation(
                source=rel_data["source"],
                target=rel_data["target"],
                relation_type=rel_data["relation_type"],
                strength=rel_data["strength"],
                context=rel_data.get("context", ""),
                examples=rel_data.get("examples", []),
                bidirectional=rel_data.get("bidirectional", False),
                created_at=datetime.fromisoformat(rel_data["created_at"]),
                updated_at=datetime.fromisoformat(rel_data["updated_at"])
            )
            system.relations.append(relation)

            # Add to graph
            system.graph.add_edge(relation.source, relation.target,
                                 relation_type=relation.relation_type,
                                 strength=relation.strength,
                                 context=relation.context,
                                 bidirectional=relation.bidirectional)

            # If bidirectional, add reverse relation
            if relation.bidirectional:
                reverse_relation = LanguageRelation(
                    source=relation.target,
                    target=relation.source,
                    relation_type=relation.relation_type,
                    strength=relation.strength,
                    context=relation.context,
                    bidirectional=True,
                    created_at=relation.created_at,
                    updated_at=relation.updated_at
                )
                system.relations.append(reverse_relation)
                system.graph.add_edge(relation.target, relation.source,
                                     relation_type=relation.relation_type,
                                     strength=relation.strength,
                                     context=relation.context,
                                     bidirectional=True)

        # Update category hierarchy
        system._update_category_hierarchy()

        return system
