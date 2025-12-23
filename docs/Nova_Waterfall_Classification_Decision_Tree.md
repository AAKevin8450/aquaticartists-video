# Nova Waterfall Classification — Decision Tree (AA / Genesis)

This document defines the **complete decision logic** Nova should use to classify waterfall content in raw video.

## Taxonomy (4 dimensions)

1. **Family**: `Custom Natural Stone` | `Custom Formal` | `Genesis Natural` | `Genesis Formal` | `Unknown`
2. **Tier Level**: `Classic (Small)` | `Deluxe (Medium)` | `Ultimate (Large)` | `Unknown`
3. **Functional Type**: `Waterfall` | `Waterfall with Slide` | `Grotto` | `Grotto with Slide` | `Unknown`
4. **Sub-Type**: `One-Tier` | `Two-Tier` | `Two-Tier Split` | `Three-Tier` | `Cantilever` | `Unknown`

> Output must include all 4 dimensions. If any dimension cannot be determined confidently, output `Unknown` for that dimension and include a reason.

---

## Inputs Nova may use (ranked by reliability)

1. **Visual evidence** (highest): geometry, materials, presence of slide/grotto, number of drops, spill edge shape.
2. **Spoken narration / on-screen text**: brand and product words (e.g., “Genesis”, “kit”, “formal”, “grotto”, “cantilever”).
3. **Context / environment cues**: heavy machinery, build scale, jobsite complexity, site integration.

---

## Decision Order (strict)

1. Determine **Family**
2. Determine **Functional Type**
3. Determine **Tier Level**
4. Determine **Sub-Type**

Reason: Family + Functional Type are most visually distinct and least ambiguous; Tier and Sub-Type depend on those.

---

# Step 1 — Determine Family (4 Types)

Nova must choose **one** of these four Families.

## Family Definitions (clarified)

### 1) Genesis Natural (KIT + BOULDERS)
Standardized “kit” waterfalls made with **natural boulders**. Often compact and repeatable in layout.

### 2) Custom Natural Stone (CUSTOM + BOULDERS)
Bespoke Aquatic Artists features built from **natural boulders** and custom rockwork. Typically more integrated, varied, and often larger/complex.

### 3) Genesis Formal (KIT + NO BOULDERS)
Standardized “formal” kits: **rectilinear/modern geometry** made with **veneer/caps** and clean spill edges. **No boulders.**

### 4) Custom Formal (CUSTOM + NO BOULDERS)
Large bespoke formal features (Aquatic Artists custom) that use **veneer, marble, stone caps, tile/other coverings**, and modern geometry. **No boulders.**

---

## 1A) First split: Boulder vs No Boulder (fastest rule)

**Rule A (Boulder present):**
- If the feature’s primary construction is **natural boulders** (irregular rounded/angled stones, stacked rockwork that reads as “boulder waterfall”), then Family must be:
  - `Genesis Natural` **or** `Custom Natural Stone`

**Rule B (No boulders):**
- If the feature is **not** built from boulders (it’s rectilinear, veneer-faced, slab-capped, tiled, marble/stone faced, etc.), then Family must be:
  - `Genesis Formal` **or** `Custom Formal`

> IMPORTANT: “Some rock around a formal feature” does not change this. If the **water-producing structure** is formal/veneer/capped (and not a boulder stack), treat it as **Formal**.

---

## 1B) Second split: Genesis (kit) vs Custom (bespoke)

After deciding Boulder vs No Boulder, decide whether it’s a **Genesis kit** or a **Custom** build.

### Genesis (kit) indicators (use for both Natural & Formal)
**Primary kit cues (visual + contextual):**
- Layout looks **repeatable/staged** (like a “productized” unit)
- Compact footprint and relatively simple integration
- Often appears “finished on all sides” (rear/side facing is intentionally composed)
- Install content emphasizes speed/simplicity (often “install in a day”)
- Spoken cues: “Genesis”, “kit”, “single/double”, “corner”

**If most kit cues are present → choose Genesis (Natural or Formal depending on boulder/no boulder).**

### Custom (bespoke) indicators (use for both Natural & Formal)
**Primary custom cues (visual + contextual):**
- Highly site-specific geometry and integration (custom curves, multi-zone terraces, unique openings)
- Larger complexity footprint: deep excavation, large staging, multiple build days visible
- Heavy equipment (crane, skid steer frequently moving large pieces), large plumbing runs, multiple circuits
- Spoken cues: “custom”, “Aquatic Artists”, “project update”, “designed for this backyard”, etc.

**If most custom cues are present → choose Custom (Natural Stone or Formal depending on boulder/no boulder).**

---

## 1C) Family assignment (final rules)

### If BOULDERS are present
- If **kit cues dominate** → **Family = Genesis Natural**
- If **bespoke cues dominate** → **Family = Custom Natural Stone**

### If NO BOULDERS are present
- If **kit cues dominate** (standard rectilinear unit, repeatable build, “Genesis” language) → **Family = Genesis Formal**
- If **bespoke cues dominate** (large formal statement piece, custom sizes/geometry, premium coverings, heavy integration) → **Family = Custom Formal**

---

## Family Conflict Resolution (strict)

1. **Boulder present?** If yes → Natural families only (Genesis Natural / Custom Natural Stone). If no → Formal families only (Genesis Formal / Custom Formal).
2. Within Natural/Formal: if explicit “Genesis kit” language or strong kit visuals → pick the Genesis option.
3. If the feature is very large/complex and clearly custom-built on site → pick the Custom option.
4. If still unclear → `Unknown` with reason (e.g., “Boulder presence unclear due to close-up shots” or “Cannot determine kit vs custom from this segment”).

---

# Step 2 — Determine Functional Type

Functional Type is based on **presence of slide and/or grotto cavity**.

## 2A) Detect Slide (binary)
**Visual identifiers:**
- Visible slide chute (fiberglass/plastic surface) OR
- Ladder to slide OR
- Landscape slide route integrated into rockwork with **stairs/steps** and handholds/railings

If present: `has_slide = true`

## 2B) Detect Grotto (binary)
**Visual identifiers:**
- A **cave/overhang** large enough for people (seating, standing space, shaded cavity)
- “Roof” spanning an opening (grotto top)
- Camera shots from inside looking out

If present: `has_grotto = true`

## 2C) Assign Functional Type
- if `has_grotto = false` and `has_slide = false` → **Waterfall**
- if `has_grotto = false` and `has_slide = true`  → **Waterfall with Slide**
- if `has_grotto = true`  and `has_slide = false` → **Grotto**
- if `has_grotto = true`  and `has_slide = true`  → **Grotto with Slide**

**Conflict rule:**
- If grotto cavity is visible, set `has_grotto = true` even if narration says “waterfall”.

---

# Step 3 — Determine Tier Level (Classic / Deluxe / Ultimate)

Tier is a **size/complexity** classification. Nova should use a weighted combination of:
- **Approximate height** of the main waterfall face (relative to pool beam, human body, ladder steps)
- **Approximate width** of the feature along the pool edge
- **Largest element size** (boulder size for natural; face/cap scale for formal) vs human scale
- **Overall footprint** (depth off pool, terracing, multiple areas)
- **Project complexity** (multiple circuits, extensive plumbing, large equipment)

## 3A) Classic (Small)
Use `Classic` if most of these are true:
- Height appears roughly **1.5–2 ft**
- Width appears roughly **8–10 ft**
- Slide version uses a **ladder** (common for smaller slide installs)
- Minimal terracing; compact composition

## 3B) Deluxe (Medium)
Use `Deluxe` if most of these are true:
- Height appears roughly **2.5–3 ft**
- Width appears roughly **12–14 ft**
- Slide version is a **landscape slide** (no ladder) with **steps required**
- More robust rockwork/structure and footprint than Classic

## 3C) Ultimate (Large)
Use `Ultimate` if any of these are strongly true:
- Clearly “backyard water park” scale
- Very large footprint or very large elements (boulders or formal wall massing)
- Heavy machinery and/or massive material volumes
- Complex multi-feature systems (grotto + slide + multiple cascades, etc.)

**Tier Conflict Resolution:**
- If strong Ultimate cues exist (massive footprint/complexity), choose **Ultimate** even if width/height are uncertain.
- If both Classic and Deluxe cues exist, prefer **Deluxe** when there are stairs/landscape slide or clearly larger footprint.

**If uncertain:**
- Output Tier = `Unknown` with reason: “Insufficient scale reference / no reliable height & width cues.”

---

# Step 4 — Determine Sub-Type (tiers / split / cantilever)

Sub-Type describes **how water is formed and how many distinct drops/cascades exist**.

## 4A) One-Tier
**Definition:**
- One primary drop from spill edge directly into pool

**Visual identifiers:**
- No intermediate shelf where water lands before pool
- Water originates near the pool edge

## 4B) Two-Tier
**Definition:**
- Two distinct drops: water falls to an intermediate shelf/landing, then falls into pool

**Visual identifiers:**
- A visible middle shelf/step where water breaks before reaching the pool
- Feature starts farther “back” from the pool edge

## 4C) Two-Tier Split
**Definition:**
- A two-tier composition where the flow **splits around a boulder/divider**

**Visual identifiers:**
- Water divides into two channels (“two tongues”) around a central rock

## 4D) Three-Tier
**Definition:**
- Three distinct drops (top → mid shelf → lower shelf → pool)

**Visual identifiers:**
- Two intermediate shelves are visible (water breaks at two separate landings before pool)
- Feature begins farther back and reads as a small “stream” with three steps

## 4E) Cantilever
**Definition:**
- A prominent flat spill stone or straight spill edge projects outward over the pool (a “cantilever”), producing a clean sheet-like drop from its edge

**Visual identifiers:**
- Obvious projecting ledge/flat stone over waterline OR a distinct straight spill edge
- Water exits from a crisp edge, often as a more uniform sheet

**Sub-Type Conflict Resolution (strict priority):**
1. If a clear projecting spill edge is visible → **Cantilever**
2. Else if flow clearly splits around a central boulder → **Two-Tier Split**
3. Else if three distinct drops exist → **Three-Tier**
4. Else if two distinct drops exist → **Two-Tier**
5. Else → **One-Tier**

**If uncertain:**
- Output Sub-Type = `Unknown` with reason: “Water path not fully visible / camera angle obscures tiers.”

---

# Quick Summary (1-line logic)

1. **Boulders?** Yes → Natural (Genesis Natural vs Custom Natural Stone). No → Formal (Genesis Formal vs Custom Formal).
2. **Kit cues?** Yes → Genesis. No → Custom.
3. **Slide? / Grotto cavity?** Use the 2x2 mapping.
4. **Tier** by scale/complexity; **Sub-Type** by water path (Cantilever > Split > 3-tier > 2-tier > 1-tier).
