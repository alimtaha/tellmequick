# Demo script — "Should we buy COIN?" (investor + analyst, agent listens in)

**Setup:** A public-markets fund. **Maya Chen** (Portfolio Manager, skeptic, makes the call)
and **Ben Ortiz** (Equity Analyst, bull, blanks on specifics). They talk; the **agent**
listens in the background over LiveKit and **only speaks when it has a high-confidence
match** in the Moss index of Coinbase's parsed SEC filings.

Each beat lists the **filing it pulls** (the `data/parsed/` label → Moss doc), **why it's a
real unstructured-parsing win**, and the **verified fact**. Numbers marked ⚠️ should be
re-confirmed against the parsed chunk before demo day.

---

**B0 — Maya:** "Coinbase. I'm thinking about a position — the stock's had a run but
something feels off. Talk me through whether we buy."

---

### Beat 1 — "What just happened there?" → **8-K**
**Maya:** "Didn't they just do a big layoff? What actually happened?"
**Ben:** "Saw the headline, don't have the details off-hand."
**🤖** "Two weeks ago Coinbase cut about **14% of staff — roughly 700 roles** — a
restructuring framed as optimizing for the AI era. They also **reincorporated from Delaware
to Texas** in December, and a director, **Paul Clement, left the board** (10 → 9). — Coinbase
8-Ks, Dec 2025–May 2026"
- *Pulls:* `8-K__2026-05-05-layoffs`, `8-K__2025-12-15-texas`, `8-K__2026-04-07-board`
- *Unstructured win:* synthesizes event items across **three separate 8-Ks**.
- *Verified:* 14% / 700 / restructuring / AI present in the parsed chunk. ✅

### Beat 2 — "Are insiders bailing?" → **Form 4**  ⭐ (flips the scary headline)
**Maya:** "A 14% cut — are the execs themselves heading for the door?"
**Ben:** "Not sure, I'd have to dig through the Form 4s."
**🤖** "No open-market selling. The CFO, **Alesia Haas, sold ~$2M (10,020 shares at $200)** —
but under a **pre-scheduled 10b5-1 plan**, not a discretionary dump. The COO, **Emilie Choi,
vested ~340,000 shares** (RSUs) because performance targets were hit, with shares withheld
only to cover taxes. Both still hold 400K–700K+ shares. — Form 4 filings, Feb–Mar 2026"
- *Pulls:* `Form 4__haas-2026-03`, `Form 4__choi-2026-02`
- *Unstructured win:* insider transaction tables + the **10b5-1 / tax-withholding nuance**
  that turns "execs selling" into "execs aligned."
- *Verified:* Haas S-code 10,020 @ $200 + 10b5-1 footnote; Choi M-code vests + F-code
  168,275 @ $165.94 withholding. ✅

### Beat 3 — "Who else is in?" → **SC 13G**  ⭐
**Maya:** "Who else is actually in this — anyone we respect?"
**Ben:** "Index funds for sure… beyond that I'd be guessing."
**🤖** "Top holders: **Vanguard ~7.4%, BlackRock ~5.7%, Jane Street ~5.3%, ARK ~5.1%** —
passive giants, a top market-maker, and Cathie Wood's thematic fund. Roughly **a quarter of
the float** across the four. — Schedule 13G filings"
- *Pulls:* `SC 13G__vanguard`, `SC 13G__blackrock`, `SC 13G__janestreet`, `SC 13G__ark`
- *Unstructured win:* aggregates beneficial-ownership tables **across four filers**.
- *Verify ⚠️:* confirm each % against the parsed 13G chunks.

### Beat 4 — "Is the CEO paid for performance?" → **DEF 14A**  ⭐
**Maya:** "If they're cutting staff, is the CEO still printing himself a fortune?"
**Ben:** "Don't remember his package off-hand."
**🤖** "Brian Armstrong's **base salary is $350,000** — most of his ~$6.3M is multi-year
equity. The COO's package vests on **revenue, EBITDA, and relative shareholder-return**
milestones. Pay is mostly at-risk, not cash. — DEF 14A proxy"
- *Pulls:* `DEF 14A__2026`
- *Unstructured win:* the **summary-compensation table** is a classic hard parse.
- *Verify ⚠️:* confirm $350K base and ~$6.3M total against the parsed proxy chunk.

### Beat 5 — "Still a one-trick trading shop?" → **10-K (MD&A)**
**Maya:** "The bear case is they're just a trading-fee shop. Still true?"
**Ben:** "They've pushed subscriptions… don't have the split memorized."
**🤖** "Latest 10-K splits revenue into **transaction revenue** — the volatile trading-fee
line — and **subscription & services**, which they've deliberately grown to diversify.
[exact split]. — Coinbase FY2025 10-K, MD&A"
- *Pulls:* `10-K__FY2025`
- *Unstructured win:* a revenue **segment table buried in a 399-page PDF**.
- *Verify ⚠️:* fill the exact split from the parsed 10-K chunk.

### Beat 6 — "The risk they admit?" → **10-K (Risk Factors)**
**Maya:** "What's the one risk they flag hardest themselves?"
**🤖** "Their own 10-K: revenue depends heavily on **crypto trading volume and market
conditions, which are highly volatile** — a sustained downturn would materially cut revenue.
That's the concentration risk, in their words. — FY2025 10-K, Risk Factors"
- *Pulls:* `10-K__FY2025`
- *Unstructured win:* **semantic** retrieval from dense legalese in a 399-page doc.

### Beat 7 — Empty state (the honesty beat) → no match
**Maya:** "And their actual AI product roadmap — what are they shipping?"
**🤖** *(stays silent — nothing above the confidence threshold)*
**Ben:** "Yeah — that's not in the filings, they only gesture at 'the AI era.' We'd need
their product announcements." → **the agent refused to hallucinate.**

---

**B8 — Maya:** "OK — the layoff headline's scary, but insiders aren't fleeing, smart money's
in, pay's aligned, and the real risk is the known crypto-beta. That's enough to **start a
position and size it small.**"

---

## Judge-appeal cheat sheet
- **Unsiloed:** Beats 1/4/5 (multi-8-K synthesis, proxy comp table, 399-pg 10-K segment table).
- **Moss:** every beat — casual phrasing → exact chunk, instant, across 8 filing types.
- **LiveKit:** no button presses; the agent rides the natural Maya/Ben back-and-forth.
- **Honesty:** Beat 7 — refuses to answer what the filings don't contain.
