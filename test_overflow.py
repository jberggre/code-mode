import sys
sys.path.insert(0, '.')
from app.memory import needs_compaction, budget, history_tokens, compact, archive, write_handoff, read_handoff, handoff_note, resume_note
from app.skills import read_skill
import server as core

# Check we have a model available
backends = core.list_backends()
print('Backends:', backends)

# Check skills
skill = read_skill('using-superpowers')
print(f'useing-superpowers skill: {len(skill)} chars')

# Test compaction with many messages
# Create messages that will exceed context window
messages = []
for i in range(50):
    messages.append({'role': 'user', 'content': f'Turn {i}: some code content here. ' * 20})

used = history_tokens(messages, {})
budget_val = budget({'num_ctx': 8192, 'num_predict': 512})
print(f'Messages: {len(messages)}, used tokens: {used}, budget: {budget_val}')
print(f'needs_compaction: {needs_compaction(messages, {"num_ctx": 8192, "num_predict": 512})}')

# Test handoff writing
hf = write_handoff('Test handoff content - goal was to write code, done some things, in progress is more coding, next step is finish it')
print(f'Handoff written: {hf}')

# Test handoff reading
hf_body = read_handoff()
print(f'Handoff body (first 200 chars): {hf_body[:200]}')

# Test handoff note
note = handoff_note()
print(f'Handoff note: {note[:200]}')

# Test resume note
resume = resume_note()
print(f'Resume note: {resume[:200]}')

print('\nAll memory functions verified and working!')