---
name: sentigent-review
description: Review the current session's decisions through Sentigent's judgment lens
user_invocable: true
---

# Sentigent Session Review

Review the current coding session through Sentigent's judgment lens.

## Instructions

1. Call `sentigent_patterns` to get the learned patterns
2. Call `sentigent_score` to get current statistics
3. Analyze the current session's actions:
   - What files were changed?
   - Were tests run before commits?
   - Were there any destructive operations?
   - Were there any security concerns?
4. Present a judgment review:

### Format

```
🧠 Sentigent Session Review

✅ Good Decisions:
  - [List actions that align with learned patterns]

⚠️ Areas of Concern:
  - [List actions that triggered caution/doubt signals]

💡 Suggestions:
  - [Actionable suggestions based on patterns]

📊 Session Score: [computed from this session's decisions]
```

5. If there are actions that haven't been attributed yet (no outcome recorded),
   ask the developer for feedback on the most important ones
