"""
Prompt management for loading and rotating game prompts.
"""
import config


def load_prompts(filename=None):
    """
    Load prompts from a file.
    
    Args:
        filename: Path to prompts file. Defaults to config.UNUSED_PROMPTS_FILE
    
    Returns:
        List of prompt strings
    """
    if filename is None:
        filename = config.UNUSED_PROMPTS_FILE
    
    try:
        with open(filename, "r", encoding="utf-8") as f:
            prompts = [line.strip() for line in f if line.strip()]
        return prompts
    except FileNotFoundError:
        print(f"Warning: {filename} not found. Creating empty file.")
        with open(filename, "w", encoding="utf-8") as f:
            pass
        return []
    except Exception as e:
        print(f"Error loading prompts: {e}")
        return []


def move_prompt_to_used(prompt):
    """
    Move a prompt from unused_prompts.txt to used_prompts.txt.
    Uses case-insensitive comparison.
    
    Args:
        prompt: The prompt string to mark as used
    """
    try:
        # Read all unused prompts
        with open(config.UNUSED_PROMPTS_FILE, "r", encoding="utf-8") as f:
            unused = [line.strip() for line in f if line.strip()]

        # Remove the used prompt (case-insensitive)
        original_count = len(unused)
        unused = [p for p in unused if p.lower() != prompt.lower()]
        
        if len(unused) == original_count:
            print(f"Warning: Prompt '{prompt}' not found in unused prompts")

        # Write back to unused_prompts.txt
        with open(config.UNUSED_PROMPTS_FILE, "w", encoding="utf-8") as f:
            for p in unused:
                f.write(p + "\n")

        # Append to used_prompts.txt
        with open(config.USED_PROMPTS_FILE, "a", encoding="utf-8") as f:
            f.write(prompt + "\n")
    except Exception as e:
        print(f"Error moving prompt to used: {e}")


def get_random_prompt(prompt_bank):
    """
    Get a random prompt from the bank and mark it as used.
    
    Args:
        prompt_bank: List of available prompts
    
    Returns:
        Random prompt string, or None if no prompts available
    """
    if not prompt_bank:
        print("Warning: No prompts available!")
        return "Draw something cool"
    
    prompt = prompt_bank.pop(random.randint(0, len(prompt_bank) - 1))
    move_prompt_to_used(prompt)
    return prompt


# Import at end to avoid circular dependency
import random
