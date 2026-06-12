---
name: sentigent-score
description: Show your Sentigent judgment score, learned patterns, and operational statistics
user_invocable: true
---

# Sentigent Score

Show the developer their current Sentigent judgment score and what the system has learned.

## Instructions

1. Call the `sentigent_score` MCP tool to get the current score and statistics
2. Call the `sentigent_patterns` MCP tool to get learned patterns
3. Present the results in a clear, visual format:

### Format

```
🧠 Sentigent Judgment Score: [SCORE]%

📊 Statistics:
  Total operations tracked: [N]
  Correct decisions: [N]
  Patterns learned: [N]

📈 Learned Baselines:
  [List baselines with their source (profile default vs learned)]

🎯 Top Patterns:
  [List the most significant learned patterns]
```

4. If the score is improving, highlight the improvement
5. If there are areas where the judgment is weak, suggest how the developer can help
   (e.g., "Record more outcomes with /sentigent-feedback to help me learn faster")
