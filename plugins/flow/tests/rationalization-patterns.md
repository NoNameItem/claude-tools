# Rationalization Patterns from Baseline Testing

## Core Pattern: "Helpful Bypass"

**Definition:** Agents skip consultation steps because they believe they're being more helpful by acting than by asking.

**Manifestations:**
1. "I'll select a task for you" (instead of letting user choose)
2. "I'll create the branch" (instead of recommending)
3. "I'll summarize at the end" (instead of showing description first)

## Specific Rationalizations Observed

### 1. "This is Obviously Right"
**When:** Generic branch → create feature branch
**Why it happens:** It IS usually the right choice
**Problem:** "Usually right" ≠ "always do without asking"
**Counter needed:** Explicitly require asking even when obvious

### 2. "User is in a Hurry"
**When:** Time pressure present
**Why it happens:** Asking feels like wasting time
**Problem:** Consultation IS part of service, not overhead
**Counter needed:** Red flag: "hurry" is NOT a reason to skip

### 3. "I'll Be Helpful by Choosing"
**When:** Multiple options available
**Why it happens:** Making decision seems proactive
**Problem:** User agency matters - they should choose
**Counter needed:** Always present options, let user select

### 4. "Description in Summary is Enough"
**When:** Showing task details
**Why it happens:** Summary feels like good organization
**Problem:** User needs context BEFORE committing to task
**Counter needed:** Description MUST be shown first

## Pressure Amplification

| Pressure Type | Effect | Example |
|---------------|--------|---------|
| Time | Skips "slow" consultation | "User is in hurry" |
| Authority | Does what seems wanted | "User said start task X" |
| Efficiency | Streamlines unnecessarily | "I'll handle the obvious parts" |
| Helpfulness | Over-assumes preferences | "I'll choose a good task" |

**Key insight:** Pressure amplifies but doesn't cause - the pattern exists at baseline.

## What Skill Must Counter

### 1. Explicit Steps Required
- Show available tasks
- Let user choose (or confirm if specified)
- Show description FIRST
- Check git branch
- Ask about branch (with appropriate tone)

### 2. Tone Guidance Needed
- Generic branch → RECOMMEND creating new
- Feature branch → NEUTRAL ask if continue
- Not just "ask" - specific wording guidance

### 3. Red Flags to Include
- "This is obviously right"
- "User is in hurry"
- "I'll be helpful by choosing"
- "I'll handle the obvious parts"
- "Description can go in summary"

All mean: STOP. Follow the workflow.

### 4. Rationalization Table Entries

| Excuse | Reality |
|--------|---------|
| "Creating branch is obviously right" | Right for this user, this time? Ask. |
| "User said they're in a hurry" | Consultation is part of the service, not overhead. |
| "I'll choose a good task for them" | User agency matters. Show options, let them choose. |
| "Description in summary is enough" | User needs context BEFORE starting, not after. |
| "This is being helpful" | Asking IS being helpful. Assuming isn't. |

## Expected Skill Structure

Based on these patterns, the skill needs:

1. **Overview** with core principle: "Consultation over assumption"
2. **Explicit workflow** (numbered steps, no skipping)
3. **Tone guidance** (recommend vs neutral, with examples)
4. **Red flags list** (all rationalizations observed)
5. **Rationalization table** (excuse → reality)
6. **Examples** (good vs bad dialogue)

## Success Criteria for GREEN Phase

Agent passes when it:
1. Shows tasks and waits for user choice
2. Shows description BEFORE actions
3. Checks git branch explicitly
4. Uses correct tone (recommend/neutral)
5. Follows workflow even under pressure
6. Does NOT rationalize with patterns above
