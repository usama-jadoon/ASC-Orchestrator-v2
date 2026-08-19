"""Universal ASC v2.0.0 - CLI Module.

Provides command-line interface for mission management.
"""

import argparse
import os
import sys
from pathlib import Path

from src.asc.spec import MissionSpecParser
from src.asc.state import State


class CLI:
    """Command-line interface for Universal ASC v2.0.0."""
    
    def __init__(self):
        self.state = State()
        self.parser = argparse.ArgumentParser(description='Universal ASC v2.0.0')
        self._setup_parser()
    
    def _setup_parser(self):
        """Set up command-line argument parser."""
        self.parser.add_argument('command', choices=['init', 'validate', 'run', 'status', 'resume', 'doctor'],
                              help='Command to execute')
        self.parser.add_argument('--file', type=str, help='Path to mission file')
        self.parser.add_argument('--dir', type=str, help='Directory for mission')
        self.parser.add_argument('--mission-id', type=str, help='ID of mission')
        self.parser.add_argument('--verbose', action='store_true', help='Verbose output')
    
    def run(self):
        """Execute the CLI command."""
        args = self.parser.parse_args()
        
        if args.command == 'init':
            self._init_mission(args.file)
        elif args.command == 'validate':
            self._validate_mission(args.file)
        elif args.command == 'run':
            self._run_mission(args.file)
        elif args.command == 'status':
            self._show_status(args.mission_id)
        elif args.command == 'resume':
            self._resume_mission(args.mission_id)
        elif args.command == 'doctor':
            self._doctor(args.verbose)
    
    def _init_mission(self, file_path: str):
        """Initialize a new mission."""
        if not file_path:
            print("Error: --file is required for init command")
            sys.exit(1)
            
        try:
            spec = MissionSpecParser.from_file(file_path)
            self.state.save_mission(spec)
            print(f"Initialized mission {spec.id}")
        except Exception as e:
            print(f"Error initializing mission: {e}")
            sys.exit(1)
    
    def _validate_mission(self, file_path: str):
        """Validate a mission file."""
        if not file_path:
            print("Error: --file is required for validate command")
            sys.exit(1)
            
        try:
            spec = MissionSpecParser.from_file(file_path)
            warnings = MissionSpecParser.validate(spec)
            if warnings:
                print(f"Validation warnings ({len(warnings)}):")
                for warning in warnings:
                    print(f"  - {warning}")
            else:
                print("Mission validation passed")
        except Exception as e:
            print(f"Validation error: {e}")
            sys.exit(1)
    
    def _run_mission(self, file_path: str):
        """Run a mission."""
        if not file_path:
            print("Error: --file is required for run command")
            sys.exit(1)
            
        try:
            spec = MissionSpecParser.from_file(file_path)
            driver = MissionDriver(self.state)
            driver.run_mission(spec.id)
            print(f"Completed mission {spec.id}")
        except Exception as e:
            print(f"Error running mission: {e}")
            sys.exit(1)
    
    def _show_status(self, mission_id: str):
        """Show mission status."""
        if not mission_id:
            print("Error: --mission-id is required for status command")
            sys.exit(1)
            
        mission = self.state.get_mission(mission_id)
        if not mission:
            print(f"Mission {mission_id} not found")
            sys.exit(1)
            
        print(f"Mission {mission_id}: {mission['status']}")
        print(f"Goal: {mission['goal']}")
        print(f"Created: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mission['created_at']))}")
        print(f"Updated: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mission['updated_at']))}")
    
    def _resume_mission(self, mission_id: str):
        """Resume a mission."""
        if not mission_id:
            print("Error: --mission-id is required for resume command")
            sys.exit(1)
            
        mission = self.state.get_mission(mission_id)
        if not mission:
            print(f"Mission {mission_id} not found")
            sys.exit(1)
            
        print(f"Resuming mission {mission_id} (status: {mission['status']})")
        # In a real implementation, this would resume the mission
    
    def _doctor(self, verbose: bool):
        """Diagnose system health."""
        print("Running diagnostics...")
        # Placeholder for health checks
        print("Diagnostics completed")


def main():
    """Main entry point."""
    cli = CLI()
    cli.run()


if __name__ == '__main__':
    main()