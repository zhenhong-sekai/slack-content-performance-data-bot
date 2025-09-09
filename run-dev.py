#!/usr/bin/env python3
"""
Development runner with auto-reload functionality.
Monitors Python files for changes and automatically restarts the bot.
"""

import os
import sys
import time
import subprocess
import signal
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class BotReloader:
    def __init__(self, script_path="run-simple.py"):
        self.script_path = script_path
        self.process = None
        self.observer = None
        
    def start_bot(self):
        """Start the bot process."""
        if self.process:
            self.stop_bot()
        
        print(f"🚀 Starting bot: python3 {self.script_path}")
        print(f"📍 Working directory: {os.getcwd()}")
        
        # Start process with live output
        self.process = subprocess.Popen([
            sys.executable, self.script_path
        ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        
        print(f"✅ Bot process started with PID: {self.process.pid}")
        
        # Print process output in real-time
        def print_output():
            if self.process and self.process.stdout:
                try:
                    for line in iter(self.process.stdout.readline, ''):
                        if line.strip():
                            print(f"[BOT] {line.strip()}")
                        if self.process.poll() is not None:
                            break
                except Exception as e:
                    print(f"❌ Error reading bot output: {e}")
        
        import threading
        output_thread = threading.Thread(target=print_output, daemon=True)
        output_thread.start()
    
    def stop_bot(self):
        """Stop the bot process."""
        if self.process:
            print("🛑 Stopping bot...")
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print("⚠️  Force killing bot...")
                self.process.kill()
                self.process.wait()
            self.process = None
    
    def restart_bot(self):
        """Restart the bot process."""
        print("🔄 Restarting bot due to file changes...")
        self.stop_bot()
        time.sleep(1)  # Brief pause
        self.start_bot()

class CodeChangeHandler(FileSystemEventHandler):
    def __init__(self, reloader):
        self.reloader = reloader
        self.last_restart = 0
        
    def should_restart(self, event):
        """Check if we should restart based on the file change."""
        if event.is_directory:
            return False
            
        # Only watch Python files
        if not event.src_path.endswith('.py'):
            return False
            
        # Ignore __pycache__ and .pyc files
        if '__pycache__' in event.src_path or event.src_path.endswith('.pyc'):
            return False
            
        # Debounce: don't restart too frequently
        now = time.time()
        if now - self.last_restart < 2:  # 2 second debounce
            return False
            
        return True
    
    def on_modified(self, event):
        if self.should_restart(event):
            print(f"📝 File changed: {event.src_path}")
            self.last_restart = time.time()
            self.reloader.restart_bot()
    
    def on_created(self, event):
        if self.should_restart(event):
            print(f"➕ File created: {event.src_path}")
            self.last_restart = time.time()
            self.reloader.restart_bot()

def main():
    print("🔧 OptiBot Development Mode - Auto-reload enabled")
    print("📁 Watching for Python file changes in current directory...")
    print("💡 Press Ctrl+C to stop")
    print(f"🐍 Using Python: {sys.executable}")
    print()
    
    reloader = BotReloader()
    
    # Set up file watcher
    event_handler = CodeChangeHandler(reloader)
    observer = Observer()
    observer.schedule(event_handler, path='.', recursive=True)
    reloader.observer = observer
    
    def signal_handler(sig, frame):
        print("\n🛑 Shutting down development server...")
        reloader.stop_bot()
        if observer:
            observer.stop()
            observer.join()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Start initial bot
        reloader.start_bot()
        
        # Start file watcher
        observer.start()
        
        # Keep the main thread alive
        while True:
            time.sleep(1)
            
            # Check if bot process died unexpectedly
            if reloader.process and reloader.process.poll() is not None:
                print("⚠️  Bot process died, restarting...")
                reloader.start_bot()
                
    except KeyboardInterrupt:
        signal_handler(signal.SIGINT, None)

if __name__ == "__main__":
    main()