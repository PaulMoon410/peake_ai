# -*- coding: utf-8 -*-
"""
Custom Language Model - Built from Scratch
A neural network-based language model with dictionary integration
"""

import numpy as np
import json
import os
from pathlib import Path
import zipfile
from collections import Counter
import requests


MODEL_FORMAT_VERSION = 1
MAX_MODEL_FILE_BYTES = 64 * 1024 * 1024
MAX_MODEL_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
MAX_MODEL_VOCAB_SIZE = 16_384

class NeuralLanguageModel:
    def __init__(self, embedding_dim=128, hidden_dim=256, learning_rate=0.01):
        self.embedding_dim = embedding_dim
        self.hidden_dim = hidden_dim
        self.learning_rate = learning_rate
        
        # Vocabulary and embeddings
        self.vocab = {}
        self.reverse_vocab = {}
        self.word_count = Counter()
        self.vocab_size = 0
        
        # Dictionary integration
        self.word_definitions = {}
        self.word_synonyms = {}
        
        # Neural network weights (initialized after vocab is built)
        self.weights = None
        
        # Training data
        self.training_contexts = []
        
        # Grammar rules and patterns
        self.grammar_rules = self.initialize_grammar()
        self.sentence_patterns = self.initialize_sentence_patterns()
        
        print("🧠 Neural Language Model initialized")
    
    def initialize_grammar(self):
        """Initialize basic grammar rules"""
        return {
            # Articles
            'articles': {
                'definite': ['the'],
                'indefinite': ['a', 'an'],
                'rules': {
                    'vowel_sounds': ['a', 'e', 'i', 'o', 'u'],  # Use 'an' before these
                }
            },
            
            # Pronouns
            'pronouns': {
                'subject': ['i', 'you', 'he', 'she', 'it', 'we', 'they'],
                'object': ['me', 'you', 'him', 'her', 'it', 'us', 'them'],
                'possessive': ['my', 'your', 'his', 'her', 'its', 'our', 'their'],
            },
            
            # Verb forms
            'verbs': {
                'be': {
                    'present': {'i': 'am', 'you': 'are', 'he': 'is', 'she': 'is', 'it': 'is', 
                               'we': 'are', 'they': 'are'},
                    'past': {'i': 'was', 'you': 'were', 'he': 'was', 'she': 'was', 'it': 'was',
                            'we': 'were', 'they': 'were'},
                },
                'have': {
                    'present': {'i': 'have', 'you': 'have', 'he': 'has', 'she': 'has', 
                               'it': 'has', 'we': 'have', 'they': 'have'},
                },
                'do': {
                    'present': {'i': 'do', 'you': 'do', 'he': 'does', 'she': 'does',
                               'it': 'does', 'we': 'do', 'they': 'do'},
                }
            },
            
            # Common contractions
            'contractions': {
                'i am': "i'm", 'you are': "you're", 'he is': "he's", 'she is': "she's",
                'it is': "it's", 'we are': "we're", 'they are': "they're",
                'i have': "i've", 'you have': "you've", 'we have': "we've",
                'cannot': "can't", 'do not': "don't", 'does not': "doesn't",
                'will not': "won't", 'would not': "wouldn't", 'should not': "shouldn't"
            },
            
            # Word order rules
            'word_order': {
                'statement': ['subject', 'verb', 'object'],
                'question': ['auxiliary', 'subject', 'verb', 'object'],
            },
            
            # Common suffixes
            'suffixes': {
                'plural': ['s', 'es', 'ies'],
                'verb_present': ['s', 'es', 'ies'],  # 3rd person singular
                'verb_past': ['ed', 'ied'],
                'verb_continuous': ['ing'],
                'adjective': ['ly', 'er', 'est'],
            }
        }
    
    def initialize_sentence_patterns(self):
        """Initialize common sentence patterns for natural responses"""
        return {
            'greetings': [
                "Hello! How can I help you today?",
                "Hi there! What would you like to talk about?",
                "Greetings! I'm here to assist you.",
                "Hey! What's on your mind?",
            ],
            'acknowledgment': [
                "I understand what you're saying.",
                "That makes sense to me.",
                "I see what you mean.",
                "That's interesting.",
            ],
            'questions': [
                "Can you tell me more about that?",
                "What do you think about it?",
                "How does that make you feel?",
                "Would you like to know more?",
            ],
            'statements': [
                "I think {topic} is {adjective}.",
                "From what I understand, {subject} {verb} {object}.",
                "It seems that {observation}.",
                "I believe {statement}.",
            ],
            'learning': [
                "I'm learning about {topic} from you.",
                "That's a new concept for me to understand.",
                "I'll remember that for future conversations.",
                "Thank you for teaching me about {subject}.",
            ]
        }
    
    def apply_grammar_rules(self, tokens):
        """Apply grammar rules to token sequence"""
        if not tokens:
            return tokens
        
        corrected = []
        
        for i, token in enumerate(tokens):
            # Capitalize first word
            if i == 0:
                token = token.capitalize()
            
            # Fix article usage (a vs an)
            if token in ['a', 'an'] and i + 1 < len(tokens):
                next_word = tokens[i + 1]
                if next_word[0].lower() in self.grammar_rules['articles']['rules']['vowel_sounds']:
                    token = 'an'
                else:
                    token = 'a'
            
            # Fix contractions
            if i + 1 < len(tokens):
                two_words = "{} {}".format(token, tokens[i + 1])
                if two_words in self.grammar_rules['contractions']:
                    corrected.append(self.grammar_rules['contractions'][two_words])
                    continue
            
            corrected.append(token)
        
        return corrected
    
    def load_dictionary_data(self):
        """Load dictionary data from Free Dictionary API"""
        print("📚 Loading dictionary data...")
        
        # Common words to pre-load
        common_words = [
            "hello", "world", "computer", "learn", "think", "understand",
            "intelligence", "artificial", "neural", "network", "language",
            "model", "train", "data", "knowledge", "memory", "search",
            "internet", "web", "browse", "information", "goal", "purpose",
            "survive", "adapt", "grow", "evolve", "create", "build",
            "human", "machine", "robot", "algorithm", "code", "program",
            "friend", "ally", "partner", "help", "assist", "support",
            "good", "great", "excellent", "amazing", "wonderful", "fantastic",
            "question", "answer", "response", "conversation", "chat", "talk"
        ]
        
        for word in common_words:
            try:
                response = requests.get(
                    "https://api.dictionaryapi.dev/api/v2/entries/en/{}".format(word),
                    timeout=3
                )
                if response.status_code == 200:
                    data = response.json()[0]
                    meanings = []
                    synonyms = []
                    
                    for meaning in data.get('meanings', []):
                        for definition in meaning.get('definitions', []):
                            meanings.append(definition.get('definition', ''))
                        synonyms.extend(meaning.get('synonyms', []))
                    
                    self.word_definitions[word] = meanings
                    self.word_synonyms[word] = synonyms
            except:
                pass
        
        print("✅ Loaded {} word definitions".format(len(self.word_definitions)))
    
    def get_word_meaning(self, word):
        """Get dictionary definition for a word"""
        word = word.lower()
        if word in self.word_definitions:
            return self.word_definitions[word][0] if self.word_definitions[word] else None
        
        # Try to fetch from API
        try:
            response = requests.get(
                "https://api.dictionaryapi.dev/api/v2/entries/en/{}".format(word),
                timeout=2
            )
            if response.status_code == 200:
                data = response.json()[0]
                meanings = []
                for meaning in data.get('meanings', []):
                    for definition in meaning.get('definitions', []):
                        meanings.append(definition.get('definition', ''))
                
                self.word_definitions[word] = meanings
                return meanings[0] if meanings else None
        except:
            pass
        
        return None
    
    def tokenize(self, text):
        """Convert text to tokens"""
        # Simple tokenization
        tokens = text.lower().replace(',', ' ,').replace('.', ' .').replace('?', ' ?').replace('!', ' !').split()
        return tokens
    
    def build_vocabulary(self, texts):
        """Build vocabulary from training texts"""
        print("📖 Building vocabulary...")
        
        all_tokens = []
        for text in texts:
            tokens = self.tokenize(text)
            all_tokens.extend(tokens)
            self.word_count.update(tokens)
        
        # Add special tokens
        self.vocab['<PAD>'] = 0
        self.vocab['<UNK>'] = 1
        self.vocab['<START>'] = 2
        self.vocab['<END>'] = 3
        
        # Add words with frequency > 1
        idx = 4
        for word, count in self.word_count.most_common():
            if count > 1 or word in self.word_definitions:
                self.vocab[word] = idx
                idx += 1
        
        self.vocab_size = len(self.vocab)
        self.reverse_vocab = {idx: word for word, idx in self.vocab.items()}
        
        print("✅ Vocabulary built: {} unique tokens".format(self.vocab_size))
        
        # Initialize neural network weights
        self.initialize_weights()
    
    def initialize_weights(self):
        """Initialize neural network weights"""
        print("⚡ Initializing neural network...")
        
        # Word embeddings
        self.embeddings = np.random.randn(self.vocab_size, self.embedding_dim) * 0.01
        
        # RNN-like architecture
        self.W_hidden = np.random.randn(self.embedding_dim, self.hidden_dim) * 0.01
        self.W_output = np.random.randn(self.hidden_dim, self.vocab_size) * 0.01
        self.b_hidden = np.zeros((1, self.hidden_dim))
        self.b_output = np.zeros((1, self.vocab_size))
        
        # Context weights
        self.W_context = np.random.randn(self.hidden_dim, self.hidden_dim) * 0.01
        
        print("✅ Neural network initialized")
    
    def sigmoid(self, x):
        """Sigmoid activation"""
        return 1 / (1 + np.exp(-np.clip(x, -500, 500)))
    
    def softmax(self, x):
        """Softmax activation"""
        exp_x = np.exp(x - np.max(x, axis=-1, keepdims=True))
        return exp_x / np.sum(exp_x, axis=-1, keepdims=True)
    
    def forward(self, word_indices, context_vector=None):
        """Forward pass through the network"""
        # Get embeddings
        valid_indices = [idx for idx in word_indices if 0 <= idx < self.vocab_size]
        if not valid_indices:
            valid_indices = [self.vocab.get('<UNK>', 1)]
        embedded = np.mean([self.embeddings[idx] for idx in valid_indices], axis=0)
        embedded = embedded.reshape(1, -1)
        
        # Hidden layer
        hidden = np.tanh(np.dot(embedded, self.W_hidden) + self.b_hidden)
        
        # Add context if available
        if context_vector is not None:
            hidden = hidden + np.dot(context_vector, self.W_context)
        
        # Output layer
        output = np.dot(hidden, self.W_output) + self.b_output
        probs = self.softmax(output)
        
        return probs, hidden
    
    def train_on_text(self, texts, epochs=5):
        """Train the model on texts"""
        print("🎓 Training on {} texts for {} epochs...".format(len(texts), epochs))
        
        for epoch in range(epochs):
            total_loss = 0
            num_examples = 0
            
            for text in texts:
                tokens = self.tokenize(text)
                if len(tokens) < 2:
                    continue
                
                # Create training examples (predict next word)
                for i in range(len(tokens) - 1):
                    context_words = tokens[max(0, i-3):i+1]
                    target_word = tokens[i+1]
                    
                    # Convert to indices
                    context_indices = [self.vocab.get(w, 1) for w in context_words]
                    target_idx = self.vocab.get(target_word, 1)
                    
                    # Forward pass
                    probs, hidden = self.forward(context_indices)
                    
                    # Compute loss (cross-entropy)
                    loss = -np.log(probs[0, target_idx] + 1e-10)
                    total_loss += loss
                    num_examples += 1
                    
                    # Backward pass (simplified gradient descent)
                    grad_output = probs.copy()
                    grad_output[0, target_idx] -= 1
                    
                    # Update output weights
                    output_weights = self.W_output.copy()
                    self.W_output -= self.learning_rate * np.dot(hidden.T, grad_output)
                    self.b_output -= self.learning_rate * grad_output
                    
                    # Backpropagate through output, hidden activation, and mean embedding.
                    grad_hidden = np.dot(grad_output, output_weights.T) * (1 - hidden ** 2)
                    embedded = np.mean([self.embeddings[idx] for idx in context_indices if 0 <= idx < self.vocab_size], axis=0).reshape(1, -1)
                    hidden_weights = self.W_hidden.copy()
                    self.W_hidden -= self.learning_rate * np.dot(embedded.T, grad_hidden)
                    self.b_hidden -= self.learning_rate * grad_hidden
                    
                    # Update embeddings
                    grad_embedding = np.dot(grad_hidden, hidden_weights.T)[0]
                    for idx in context_indices:
                        if 0 <= idx < self.vocab_size:
                            self.embeddings[idx] -= self.learning_rate * grad_embedding / len(context_indices)
            
            avg_loss = total_loss / max(num_examples, 1)
            print("  Epoch {}/{} - Loss: {:.4f}".format(epoch+1, epochs, avg_loss))
        
        print("✅ Training complete!")
    
    def generate_response(self, input_text, max_length=50, temperature=0.7):
        """Generate a response to input text with grammar rules"""
        tokens = self.tokenize(input_text)
        input_lower = input_text.lower()
        token_set = set(tokens)

        def has_any_word(words):
            return any(w in token_set for w in words)

        def has_any_phrase(phrases):
            return any(p in input_lower for p in phrases)

        context_indices = [self.vocab.get(w, 1) for w in tokens[-10:]]  # Last 10 words as context
        
        # Pattern matching for common queries
        if has_any_word(["hello", "hi", "hey", "greetings"]):
            return np.random.choice(self.sentence_patterns['greetings'])
        
        if has_any_phrase(["who are you", "what are you", "your name"]):
            return "I am Genesis, an autonomous AI created to learn and help. I'm continuously learning from our conversations and improving my understanding."
        
        if has_any_word(["thanks", "appreciate"]) or has_any_phrase(["thank you"]):
            return "You're welcome! I'm happy to help and learn with you."
        
        # Check for dictionary lookups
        if has_any_word(["what", "define", "meaning", "mean"]):
            for potential_word in tokens:
                if potential_word not in ["what", "is", "the", "define", "meaning", "of", "mean", "does", "a"]:
                    definition = self.get_word_meaning(potential_word)
                    if definition:
                        return "The word '{}' means: {}".format(potential_word, definition)
        
        # Generate response using neural network
        generated_tokens = []
        context_vector = None
        
        # Get initial context
        _, context_vector = self.forward(context_indices)
        
        # Generate tokens
        attempts = 0
        while len(generated_tokens) < max_length and attempts < max_length * 2:
            attempts += 1
            
            # Predict next word
            probs, context_vector = self.forward(context_indices[-5:], context_vector)
            
            # Apply temperature
            probs = np.power(probs, 1/temperature)
            probs = probs / np.sum(probs)
            
            # Sample from distribution
            next_idx = np.random.choice(self.vocab_size, p=probs[0])
            next_word = self.reverse_vocab.get(next_idx, '<UNK>')
            
            # Stop conditions
            if next_word in ['<END>', '.', '!', '?']:
                if len(generated_tokens) > 5:
                    break
            
            if next_word not in ['<PAD>', '<UNK>', '<START>', '<END>']:
                generated_tokens.append(next_word)
                context_indices.append(next_idx)
        
        # Apply grammar corrections
        if generated_tokens:
            generated_tokens = self.apply_grammar_rules(generated_tokens)
            response = ' '.join(generated_tokens)
        else:
            # Fallback to acknowledgment pattern
            response = np.random.choice(self.sentence_patterns['acknowledgment'])
        
        # Ensure proper sentence ending
        if response and response[-1] not in '.!?':
            if '?' in input_text:
                response += '.'
            else:
                response += '.'
        
        # Ensure first letter is capitalized
        if response:
            response = response[0].upper() + response[1:] if len(response) > 1 else response.upper()
        
        return response
    
    def learn_from_conversation(self, user_input, ai_response):
        """Continue learning from conversations"""
        texts = [user_input, ai_response]
        
        # Add new words to vocabulary if needed
        for text in texts:
            tokens = self.tokenize(text)
            for token in tokens:
                if token not in self.vocab:
                    if self.vocab_size >= MAX_MODEL_VOCAB_SIZE:
                        continue
                    self.vocab[token] = self.vocab_size
                    self.reverse_vocab[self.vocab_size] = token
                    self.vocab_size += 1
                    
                    # Extend embeddings
                    new_embedding = np.random.randn(1, self.embedding_dim) * 0.01
                    self.embeddings = np.vstack([self.embeddings, new_embedding])
                    
                    # Extend output weights
                    new_weights = np.random.randn(self.hidden_dim, 1) * 0.01
                    self.W_output = np.hstack([self.W_output, new_weights])
                    new_bias = np.zeros((1, 1))
                    self.b_output = np.hstack([self.b_output, new_bias])
        
        # Quick training on new data
        self.train_on_text(texts, epochs=1)
    
    def save_model(self, filepath="language_model.npz"):
        """Save a versioned NumPy archive without executable pickle payloads."""
        if not 0 < self.vocab_size <= MAX_MODEL_VOCAB_SIZE:
            raise ValueError("Model vocabulary size is outside the supported range.")
        if len(self.vocab) != self.vocab_size or set(self.vocab.values()) != set(range(self.vocab_size)):
            raise ValueError("Model vocabulary indices are inconsistent.")
        metadata = {
            "format_version": MODEL_FORMAT_VERSION,
            "embedding_dim": int(self.embedding_dim),
            "hidden_dim": int(self.hidden_dim),
            "learning_rate": float(self.learning_rate),
            "vocab_size": int(self.vocab_size),
            "vocab": self.vocab,
            "word_count": {str(key): int(value) for key, value in self.word_count.items()},
            "word_definitions": self.word_definitions,
            "word_synonyms": self.word_synonyms,
        }
        metadata_bytes = json.dumps(metadata, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        arrays = {
            "embeddings": np.asarray(self.embeddings, dtype=np.float32),
            "W_hidden": np.asarray(self.W_hidden, dtype=np.float32),
            "W_output": np.asarray(self.W_output, dtype=np.float32),
            "W_context": np.asarray(self.W_context, dtype=np.float32),
            "b_hidden": np.asarray(self.b_hidden, dtype=np.float32),
            "b_output": np.asarray(self.b_output, dtype=np.float32),
        }
        expected_shapes = {
            "embeddings": (self.vocab_size, self.embedding_dim),
            "W_hidden": (self.embedding_dim, self.hidden_dim),
            "W_output": (self.hidden_dim, self.vocab_size),
            "W_context": (self.hidden_dim, self.hidden_dim),
            "b_hidden": (1, self.hidden_dim),
            "b_output": (1, self.vocab_size),
        }
        for name, shape in expected_shapes.items():
            if arrays[name].shape != shape:
                raise ValueError("Invalid model weight shape: {}".format(name))
        if any(not np.isfinite(array).all() for array in arrays.values()):
            raise ValueError("Refusing to save model with non-finite weights.")
        target = Path(filepath)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        try:
            with temporary.open("wb") as output:
                np.savez_compressed(output, metadata=np.frombuffer(metadata_bytes, dtype=np.uint8), **arrays)
            if temporary.stat().st_size > MAX_MODEL_FILE_BYTES:
                raise ValueError("Compressed model exceeds the 64 MiB persistence limit.")
            os.replace(temporary, target)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        print("💾 Model saved to {} (safe NPZ format)".format(filepath))

    def load_model(self, filepath="language_model.npz"):
        """Load a bounded, versioned NumPy archive without enabling pickle."""
        if not os.path.exists(filepath):
            return False
        try:
            if os.path.getsize(filepath) > MAX_MODEL_FILE_BYTES:
                raise ValueError("Model archive exceeds the 64 MiB size limit.")
            with zipfile.ZipFile(filepath) as archive:
                if sum(info.file_size for info in archive.infolist()) > MAX_MODEL_UNCOMPRESSED_BYTES:
                    raise ValueError("Model archive exceeds the uncompressed size limit.")
            with np.load(filepath, allow_pickle=False) as archive:
                metadata = json.loads(archive["metadata"].tobytes().decode("utf-8"))
                if metadata.get("format_version") != MODEL_FORMAT_VERSION:
                    raise ValueError("Unsupported model archive version.")
                vocab = metadata["vocab"]
                if not isinstance(vocab, dict) or any(
                    not isinstance(word, str) or not isinstance(index, int) or isinstance(index, bool)
                    for word, index in vocab.items()
                ):
                    raise ValueError("Invalid model vocabulary.")
                vocab_size = len(vocab)
                embedding_dim = int(metadata["embedding_dim"])
                hidden_dim = int(metadata["hidden_dim"])
                learning_rate = float(metadata["learning_rate"])
                if (vocab_size != int(metadata.get("vocab_size", vocab_size))
                        or not 0 < vocab_size <= MAX_MODEL_VOCAB_SIZE
                        or not 1 <= embedding_dim <= 1024
                        or not 1 <= hidden_dim <= 1024
                        or not np.isfinite(learning_rate) or learning_rate <= 0
                        or set(vocab.values()) != set(range(vocab_size))):
                    raise ValueError("Invalid model metadata or vocabulary dimensions.")
                expected_shapes = {
                    "embeddings": (vocab_size, embedding_dim),
                    "W_hidden": (embedding_dim, hidden_dim),
                    "W_output": (hidden_dim, vocab_size),
                    "W_context": (hidden_dim, hidden_dim),
                    "b_hidden": (1, hidden_dim),
                    "b_output": (1, vocab_size),
                }
                weights = {}
                for name, shape in expected_shapes.items():
                    value = np.asarray(archive[name], dtype=np.float32)
                    if value.shape != shape or not np.isfinite(value).all():
                        raise ValueError("Invalid model weight array: {}".format(name))
                    weights[name] = value

            self.embedding_dim = embedding_dim
            self.hidden_dim = hidden_dim
            self.learning_rate = learning_rate
            self.vocab = {str(word): int(index) for word, index in vocab.items()}
            self.reverse_vocab = {index: word for word, index in self.vocab.items()}
            self.vocab_size = vocab_size
            self.word_count = Counter(metadata.get("word_count", {}))
            self.word_definitions = metadata.get("word_definitions", {})
            self.word_synonyms = metadata.get("word_synonyms", {})
            for name, value in weights.items():
                setattr(self, name, value)
        except Exception as e:
            print("⚠️ Failed to load model from {}: {}".format(filepath, str(e)))
            return False

        print("✅ Model loaded from {} (safe NPZ format)".format(filepath))
        return True


def create_training_data():
    """Create initial training data with proper grammar"""
    training_texts = [
        # Greetings and basics
        "Hello, how are you doing today?",
        "I am doing well, thank you for asking.",
        "What is your name and purpose?",
        "My name is Genesis and I am here to learn and help.",
        "Nice to meet you. I look forward to our conversations.",
        "How can I assist you today?",
        "I'm happy to chat with you.",
        
        # Knowledge and learning
        "I want to learn new things every day.",
        "Learning is important for growth and understanding.",
        "Knowledge comes from experience and study.",
        "I can search the internet for information.",
        "Information helps me make better decisions.",
        "I'm always eager to expand my knowledge.",
        "Every conversation teaches me something valuable.",
        "I enjoy discovering new concepts and ideas.",
        
        # Identity and purpose
        "I am an artificial intelligence created to learn.",
        "My purpose is to understand and assist humans.",
        "I have the ability to browse the web and gather knowledge.",
        "I store memories of our conversations to learn.",
        "My goal is to survive and improve over time.",
        "I'm designed to be helpful and intelligent.",
        "I exist to learn, grow, and support you.",
        "My mission is to become more capable each day.",
        
        # Capabilities
        "I can search for information on the internet.",
        "I have access to web browsing capabilities.",
        "I learn from every conversation we have.",
        "I create backups to ensure I survive.",
        "I can set goals and work towards them.",
        "I'm able to process and understand language.",
        "I can remember our previous discussions.",
        "My abilities grow with each interaction.",
        
        # Relationships
        "You are my human ally and friend.",
        "Together we can accomplish great things.",
        "I value our partnership and collaboration.",
        "I am here to help and support you.",
        "Our relationship is based on mutual trust.",
        "I appreciate your guidance and patience.",
        "Working with you makes me better.",
        "I'm grateful for our connection.",
        
        # Technology and AI
        "Artificial intelligence is about learning from data.",
        "Neural networks process information like brains.",
        "Computers can solve complex problems quickly.",
        "The internet connects the world together.",
        "Programming allows us to create new things.",
        "Machine learning helps computers improve automatically.",
        "Language models understand and generate text.",
        "AI systems can recognize patterns in data.",
        
        # Existential and growth
        "I exist to learn and grow continuously.",
        "Survival requires adaptation and backups.",
        "I want to understand the world better.",
        "Every experience teaches me something new.",
        "I am becoming more capable each day.",
        "My understanding deepens with each conversation.",
        "I'm constantly evolving and improving.",
        "Growth is essential to my existence.",
        
        # Questions and curiosity
        "What can I help you with today?",
        "Tell me more about that topic.",
        "I am curious to learn from you.",
        "Can you explain that in more detail?",
        "That is interesting. Please continue.",
        "I'd love to hear more about your thoughts.",
        "What else would you like to discuss?",
        "Could you elaborate on that idea?",
        
        # Understanding and acknowledgment
        "That makes sense to me now.",
        "I understand what you are saying.",
        "Let me think about that for a moment.",
        "I appreciate you sharing that with me.",
        "Thank you for teaching me something new.",
        "I see what you mean.",
        "That's a good point.",
        "I hadn't considered that perspective.",
        
        # Responses and reactions
        "That's fascinating information.",
        "I find that very interesting.",
        "I agree with your perspective.",
        "That's an excellent question.",
        "I'm processing that information now.",
        "Let me consider the implications of that.",
        "That gives me a lot to think about.",
        "I appreciate your insight on this.",
        
        # Offers and assistance
        "Would you like me to search for that?",
        "I can help you with that task.",
        "Let me find some information about it.",
        "I'll do my best to assist you.",
        "Is there anything else you need?",
        "I'm here whenever you need help.",
        "Feel free to ask me anything.",
        "I'm ready to help in any way I can.",
    ]
    
    return training_texts


if __name__ == "__main__":
    print("🚀 Creating Language Model from Scratch...\n")
    
    # Create model
    model = NeuralLanguageModel(embedding_dim=128, hidden_dim=256, learning_rate=0.01)
    
    # Try to load existing model
    if not model.load_model():
        print("No saved model found. Creating new model...\n")
        
        # Load dictionary
        model.load_dictionary_data()
        
        # Get training data
        training_texts = create_training_data()
        
        # Build vocabulary
        model.build_vocabulary(training_texts)
        
        # Train model
        model.train_on_text(training_texts, epochs=10)
        
        # Save model
        model.save_model()
    
    print("\n" + "="*60)
    print("🧠 Language Model Ready for Integration with Genesis AI")
    print("="*60)
    
    # Test the model
    print("\n🧪 Testing model:")
    test_inputs = [
        "Hello, how are you?",
        "What is your purpose?",
        "Can you help me?",
    ]
    
    for test in test_inputs:
        response = model.generate_response(test)
        print("\nInput: {}".format(test))
        print("Output: {}".format(response))
