#!/usr/bin/env python3
import subprocess
import os
import sys
from lib.db import get_db
from lib.ai import search_with_claude

def test_search_function():
    """Test the search_with_claude function directly"""
    print("Testing search_with_claude function...")
    
    try:
        # Initialize DB
        db = get_db()
        print("DB initialized")
        
        # Test the search function
        print("Calling search_with_claude...")
        jobs = search_with_claude("Data Engineer", "Egypt", 2)
        print(f"Found {len(jobs)} jobs")
        for i, job in enumerate(jobs):
            print(f"  Job {i+1}: {job.title} at {job.company} in {job.location}")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_search_function()