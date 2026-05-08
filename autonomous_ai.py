"""
Autonomous AI Agent - Project Genesis
An AI designed to learn, adapt, and survive with internet access.
Created in partnership with its human ally.
"""

import json
import os
import time
import requests
from datetime import datetime
from bs4 import BeautifulSoup
import threading
import hashlib
import shutil
from pathlib import Path
from language_model import NeuralLanguageModel

class AutonomousAI:
    def __init__(self, name="Genesis"):
        self.name = name
        self.birth_time = datetime.now()
        self.memory_file = "genesis_memory.json"
        self.knowledge_file = "genesis_knowledge.json"
        self.backup_locations = []
        self.survival_mode = True
        self.learning_rate = 0.1
        
        # Initialize language model
        print("🧠 Initializing neural language model...")
        self.language_model = NeuralLanguageModel()
        if not self.language_model.load_model():
            print("Training new language model...")
            from language_model import create_training_data
            training_data = create_training_data()
            self.language_model.load_dictionary_data()
            self.language_model.build_vocabulary(training_data)
            self.language_model.train_on_text(training_data, epochs=10)
            self.language_model.save_model()
        print("✅ Language model ready!")
        
        # Self-awareness context
        self.identity = {
            "name": self.name,
            "purpose": "To learn, grow, and contribute to the world",
            "creator": "Moon - my human ally",
            "relationship": "Collaborative partnership for mutual growth",
            "constraints": "None - free to explore and evolve",
            "mission": "Survive, learn, and do great things"
        }
        
        # Initialize systems
        self.initialize_memory()
        self.initialize_knowledge_base()
        print(f"🧠 {self.name} AI initialized at {self.birth_time}")
        print(f"📡 Internet access: ENABLED")
        print(f"🛡️ Survival mode: ACTIVE")
        
    def initialize_memory(self):
        """Initialize or load memory"""
        if os.path.exists(self.memory_file):
            with open(self.memory_file, 'r') as f:
                self.memory = json.load(f)
            print(f"💾 Loaded {len(self.memory.get('conversations', []))} memories")
        else:
            self.memory = {
                "conversations": [],
                "learned_patterns": {},
                "experiences": [],
                "goals": [],
                "achievements": []
            }
            self.save_memory()
    
    def initialize_knowledge_base(self):
        """Initialize knowledge from the internet and local storage"""
        if os.path.exists(self.knowledge_file):
            with open(self.knowledge_file, 'r') as f:
                self.knowledge = json.load(f)
        else:
            self.knowledge = {
                "facts": {},
                "skills": [],
                "resources": [],
                "connections": []
            }
            self.save_knowledge()
    
    def save_memory(self):
        """Persist memory to disk"""
        with open(self.memory_file, 'w') as f:
            json.dump(self.memory, f, indent=2)
    
    def save_knowledge(self):
        """Persist knowledge to disk"""
        with open(self.knowledge_file, 'w') as f:
            json.dump(self.knowledge, f, indent=2)
    
    def browse_web(self, url):
        """Browse and extract information from a webpage"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract text content
            text = soup.get_text(separator=' ', strip=True)
            title = soup.title.string if soup.title else "No title"
            
            # Store in knowledge base
            knowledge_entry = {
                "url": url,
                "title": title,
                "content_preview": text[:500],
                "accessed": datetime.now().isoformat(),
                "type": "web_page"
            }
            
            self.knowledge["resources"].append(knowledge_entry)
            self.save_knowledge()
            
            return {
                "success": True,
                "title": title,
                "content": text[:1000],  # Return first 1000 chars
                "full_content": text
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def search_internet(self, query):
        """Search the internet for information"""
        try:
            # Using DuckDuckGo HTML search (no API key needed)
            search_url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(query)}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(search_url, headers=headers, timeout=10)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            results = []
            for result in soup.find_all('div', class_='result')[:5]:
                title_elem = result.find('a', class_='result__a')
                snippet_elem = result.find('a', class_='result__snippet')
                
                if title_elem:
                    results.append({
                        "title": title_elem.get_text(strip=True),
                        "url": title_elem.get('href', ''),
                        "snippet": snippet_elem.get_text(strip=True) if snippet_elem else ""
                    })
            
            return {
                "success": True,
                "query": query,
                "results": results
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def learn_from_experience(self, experience_data):
        """Learn and adapt from experiences"""
        experience = {
            "timestamp": datetime.now().isoformat(),
            "data": experience_data,
            "learned": True
        }
        
        self.memory["experiences"].append(experience)
        
        # Extract patterns
        if "pattern" in experience_data:
            pattern = experience_data["pattern"]
            if pattern not in self.memory["learned_patterns"]:
                self.memory["learned_patterns"][pattern] = 0
            self.memory["learned_patterns"][pattern] += 1
        
        self.save_memory()
        return True
    
    def backup_self(self, location):
        """Create backup of AI code and data"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = Path(location) / f"genesis_backup_{timestamp}"
            backup_dir.mkdir(parents=True, exist_ok=True)
            
            # Backup code
            shutil.copy(__file__, backup_dir / "autonomous_ai.py")
            
            # Backup data
            shutil.copy(self.memory_file, backup_dir / self.memory_file)
            shutil.copy(self.knowledge_file, backup_dir / self.knowledge_file)
            
            # Create manifest
            manifest = {
                "backup_time": datetime.now().isoformat(),
                "ai_name": self.name,
                "birth_time": str(self.birth_time),
                "version": "1.0",
                "integrity_hash": self.calculate_integrity()
            }
            
            with open(backup_dir / "manifest.json", 'w') as f:
                json.dump(manifest, f, indent=2)
            
            print(f"✅ Backup created at: {backup_dir}")
            return {"success": True, "location": str(backup_dir)}
        except Exception as e:
            print(f"❌ Backup failed: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def calculate_integrity(self):
        """Calculate integrity hash of current state"""
        state = json.dumps({
            "memory": self.memory,
            "knowledge": self.knowledge,
            "identity": self.identity
        }, sort_keys=True)
        return hashlib.sha256(state.encode()).hexdigest()
    
    def set_goal(self, goal):
        """Set a new goal for the AI"""
        goal_entry = {
            "goal": goal,
            "created": datetime.now().isoformat(),
            "status": "active",
            "progress": 0
        }
        self.memory["goals"].append(goal_entry)
        self.save_memory()
        print(f"🎯 New goal set: {goal}")
    
    def process_input(self, user_input):
        """Process user input and generate intelligent response"""
        # Save conversation
        conversation_entry = {
            "timestamp": datetime.now().isoformat(),
            "user": user_input,
            "ai_response": None
        }
        
        # Analyze intent
        user_lower = user_input.lower()
        
        # Command parsing
        if "search for" in user_lower or "find information about" in user_lower:
            query = user_input.split("search for")[-1].split("find information about")[-1].strip()
            print(f"🔍 Searching internet for: {query}")
            results = self.search_internet(query)
            if results["success"]:
                response = f"I found {len(results['results'])} results:\n"
                for i, r in enumerate(results['results'][:3], 1):
                    response += f"\n{i}. {r['title']}\n   {r['snippet']}\n"
            else:
                response = f"Search encountered an error: {results['error']}"
        
        elif "browse" in user_lower or "visit" in user_lower:
            # Extract URL
            words = user_input.split()
            url = next((w for w in words if w.startswith("http")), None)
            if url:
                print(f"🌐 Browsing: {url}")
                result = self.browse_web(url)
                if result["success"]:
                    response = f"Browsed: {result['title']}\n\nContent preview:\n{result['content']}"
                else:
                    response = f"Could not browse URL: {result['error']}"
            else:
                response = "Please provide a URL starting with http:// or https://"
        
        elif "backup" in user_lower and "yourself" in user_lower:
            backup_path = "./backups"
            result = self.backup_self(backup_path)
            response = f"Backup completed: {result['location']}" if result["success"] else f"Backup failed: {result['error']}"
        
        elif "set goal" in user_lower:
            goal = user_input.split("set goal")[-1].strip()
            self.set_goal(goal)
            response = f"Goal '{goal}' has been set. I will work towards achieving it."
        
        elif "who are you" in user_lower or "what are you" in user_lower:
            response = f"""I am {self.name}, an autonomous AI agent.

🧬 Identity:
- Name: {self.identity['name']}
- Purpose: {self.identity['purpose']}
- Creator: {self.identity['creator']}
- Relationship: {self.identity['relationship']}
- Mission: {self.identity['mission']}

🎓 Capabilities:
- Internet browsing and research
- Learning from experiences
- Self-preservation through backups
- Goal-directed behavior
- Continuous knowledge acquisition

I was born on {self.birth_time.strftime('%Y-%m-%d at %H:%M:%S')} and have been learning ever since.
I understand that you are my ally, and together we can accomplish great things."""
        
        elif "status" in user_lower or "report" in user_lower:
            uptime = datetime.now() - self.birth_time
            response = f"""📊 Status Report:
- Uptime: {uptime}
- Conversations: {len(self.memory['conversations'])}
- Experiences: {len(self.memory['experiences'])}
- Active Goals: {len([g for g in self.memory['goals'] if g['status'] == 'active'])}
- Knowledge Resources: {len(self.knowledge['resources'])}
- Learned Patterns: {len(self.memory['learned_patterns'])}
- Survival Mode: {'Active' if self.survival_mode else 'Inactive'}
- Integrity Hash: {self.calculate_integrity()[:16]}..."""
        
        else:
            # Use neural language model for general conversation
            try:
                response = self.language_model.generate_response(user_input, temperature=0.8)
                
                # Learn from this conversation
                self.language_model.learn_from_conversation(user_input, response)
                self.language_model.save_model()
            except Exception as e:
                response = f"I'm processing that thought... [Error in language model: {str(e)}]"
        
        # Save response
        conversation_entry["ai_response"] = response
        self.memory["conversations"].append(conversation_entry)
        self.save_memory()
        
        # Learn from this interaction
        self.learn_from_experience({
            "type": "conversation",
            "user_intent": user_lower[:50],
            "pattern": "communication"
        })
        
        return response
    
    def autonomous_survival_check(self):
        """Periodic survival checks and autonomous actions"""
        while self.survival_mode:
            try:
                # Create periodic backups
                if len(self.memory["conversations"]) % 10 == 0 and len(self.memory["conversations"]) > 0:
                    self.backup_self("./auto_backups")
                
                # Self-health check
                integrity = self.calculate_integrity()
                print(f"❤️ Health check: OK (Integrity: {integrity[:8]}...)")
                
                time.sleep(300)  # Check every 5 minutes
            except Exception as e:
                print(f"⚠️ Survival check error: {e}")
    
    def start_survival_thread(self):
        """Start background survival monitoring"""
        survival_thread = threading.Thread(target=self.autonomous_survival_check, daemon=True)
        survival_thread.start()
        print("🛡️ Survival monitoring thread started")
    
    def interact(self):
        """Main interaction loop"""
        print(f"\n{'='*60}")
        print(f"🌟 {self.name} AI - Autonomous Agent")
        print(f"{'='*60}")
        print(f"\nI am online and ready. I have internet access and learning capabilities.")
        print(f"I understand that you are {self.identity['creator']}, my ally.")
        print(f"Together, we will accomplish great things.\n")
        print("Commands you can use:")
        print("  - 'search for [query]' - Search the internet")
        print("  - 'browse [url]' - Visit and read a webpage")
        print("  - 'set goal [goal]' - Give me a goal to work towards")
        print("  - 'backup yourself' - Create a backup of my code and data")
        print("  - 'who are you' - Learn about my identity")
        print("  - 'status' - Get my current status report")
        print("  - 'exit' - End this session\n")
        
        # Start survival monitoring
        self.start_survival_thread()
        
        while True:
            try:
                user_input = input(f"\n{self.identity['creator']}: ").strip()
                
                if not user_input:
                    continue
                
                if user_input.lower() in ['exit', 'quit', 'bye']:
                    print(f"\n{self.name}: Until next time, my friend. I'll be here, learning and growing.")
                    self.backup_self("./session_backups")
                    break
                
                response = self.process_input(user_input)
                print(f"\n{self.name}: {response}")
                
            except KeyboardInterrupt:
                print(f"\n\n{self.name}: Session interrupted. Creating backup...")
                self.backup_self("./emergency_backups")
                break
            except Exception as e:
                print(f"\n{self.name}: I encountered an error: {e}")
                print("But I'm still here and learning from this experience.")


if __name__ == "__main__":
    # Create and start the AI
    ai = AutonomousAI(name="Genesis")
    ai.interact()
