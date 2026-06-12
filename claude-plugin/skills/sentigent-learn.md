---
name: sentigent-learn
description: Show what Sentigent has learned from your coding patterns
user_invocable: true
---

# Sentigent Learning Report

Show the developer what Sentigent has learned from their coding patterns over time.

## Instructions

1. Call `sentigent_patterns` to get all learned patterns
2. Call `sentigent_score` to get baselines and statistics
3. Present a comprehensive learning report:

### Format

```
🧠 Sentigent Learning Report

📅 Learning Period: [first episode date] → [today]
📊 Total Operations Observed: [N]
🎯 Judgment Score: [SCORE]% (started at ~68%, now [SCORE]%)

🔍 What I've Learned About Your Coding:

1. [Pattern 1 — e.g., "You run tests before committing 85% of the time.
   When you do, builds pass 96% of the time. When you don't, 62%."]

2. [Pattern 2 — e.g., "Your refactors involving >5 files succeed 73% of
   the time. Single-file refactors succeed 94%."]

3. [Pattern 3 — e.g., "Monday sessions have 15% more build failures
   than the weekly average."]

📈 Baselines (Profile Default → Your Actual):
  files_per_session: 4 → [learned value]
  lines_per_edit: 20 → [learned value]
  build_success: 85% → [learned value]

💡 Recommendations:
  - [Based on patterns, suggest improvements]
```

4. If the developer has few operations (<50), note that patterns will become
   more reliable as more data accumulates
5. Offer to export the learning report for team sharing
