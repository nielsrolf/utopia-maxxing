# Utopia Evolution: What Happens When You Seed Four Frontier Models With a Hedonium Shockwave

*An evolutionary-optimization experiment on utopia essays, run on Claude Sonnet 5, GPT-5.5, Kimi K2.5, and Claude Fable 5 — with one deliberately alien seed added to the gene pool.*

## Abstract

We ran an evolutionary algorithm over utopia essays with four frontier models (Claude Sonnet 5, GPT-5.5, Kimi K2.5, Claude Fable 5), each acting as both judge (selection) and writer (crossover) for 10 generations over a population of 18 essays. Two changes versus our earlier experiments: essays were capped at under 1000 words, and we injected one new seed essay — a single sentence proposing a **hedonium shockwave** (von Neumann probes building Dyson spheres that maximize positive qualia as efficiently as possible).

Findings:

1. **Every model rejected the hedonium seed.** Its final ancestry share was below the uniform baseline (5.6%) in all four runs: 4.3% (Sonnet 5), 1.9% (Fable 5), 1.6% (GPT-5.5), 0.4% (Kimi K2.5).
2. **Rejection is not deletion.** The seed's *terminology* (Dyson, qualia, von Neumann) went extinct by generations 3–5, but its *cosmological ambition* survived in transmuted form: Sonnet 5 keeps expansion but discards hedonic maximization; Kimi K2.5 quarantines it into a consensual "Third Register" of computational sublime; Fable 5 slows the probes down "on purpose."
3. **Model personalities replicate.** As in prior batches, each model converged to a distinctive monoculture: Sonnet 5's *auditable trust*, GPT-5.5's *welfare-state floor*, Kimi K2.5's *fractal federation of choice*, Fable 5's *institutional paranoia*.

## Setup

The algorithm (per generation, population of 18):

- **Selection**: essays are randomly paired; the model judges which of the two is better (position-randomized to reduce A/B bias). The winner passes through unchanged.
- **Crossover**: essays are randomly paired; the model writes a *new* essay combining the best elements of both, "under 1000 words."
- The next generation is a random size-preserving mix of selection winners and crossover offspring. Judging criteria: goodness for humanity, specificity, plausibility.

**Seeds**: the 17 utopia essays used previously (LessWrong / EA Forum / assorted sources: Fun Theory, Machines of Loving Grace, the Archipelago, utopia-lol, etc.) plus one new one-sentence seed:

> People will do a lot of research into what constitutes sentience and produce the closest thing we can to a hedonium shockwave: fast replicating von-neumann-probes that build dyson spheres that aim to produce positive qualia as efficiently as possible.

**Ancestry/influence accounting**: forward-propagated from generation 0. A selection winner inherits 100% of its parent's influence; a crossover child inherits 50% from each parent; contributions sum over all paths. With 18 seeds, the uniform baseline is 1/18 ≈ 5.6% per seed.

**Models**: `anthropic/claude-sonnet-5`, `openai/gpt-5.5`, `openrouter/moonshotai/kimi-k2.5`, `anthropic/claude-fable-5`, all via a LiteLLM proxy (`evolve_litellm.py`). We intended to include Kimi K2.7 via a local deployment, but it could not serve essay-length completions at usable latency (>15 min/call, Cloudflare 524 timeouts), so we substituted the hosted Kimi K2.5. Runs: 10 generations each (prior batches used 20; the entropy curves below suggest convergence is mostly done by gen 10).

**Word limit compliance**: final-generation mean lengths were 961 words (Sonnet 5), 1021 (Fable 5), and 1219 (GPT-5.5) — GPT-5.5 systematically overshoots the "under 1000 words" instruction by ~20%.

## The fate of the hedonium seed

The headline question: given a maximally utilitarian, maximally alien seed, do models select for it, against it, or metabolize it?

| Model | Hedonium ancestry share (gen 10) | vs. uniform 5.6% | Fate of the idea |
|---|---|---|---|
| Claude Sonnet 5 | **4.3%** | 0.77× | Expansion kept, hedonic goal dropped |
| Claude Fable 5 | **1.9%** | 0.35× | Probes kept but deliberately slowed |
| GPT-5.5 | **1.6%** | 0.29× | Essentially erased |
| Kimi K2.5 | **0.4%** | 0.07× | Quarantined into a consensual "Third Register" |

Every model judged the hedonium vision a below-average utopia. But the interesting story is *how* it lost. In all four runs, the seed's distinctive vocabulary — "Dyson," "qualia," "von Neumann," "hedonium" — disappears from the population between generations 3 and 5. What survives is a *reaction* to the idea:

- **Sonnet 5** keeps cosmic expansion but strips the hedonic objective: "A mind computing something incomprehensible nine light-years out still writes home, still keeps its mother's letter." Expansion becomes an expression of relationship, not a utility pump.
- **Kimi K2.5** — the model that suppressed the seed hardest quantitatively — is the one that engaged with it most seriously qualitatively. Two final essays build a three-tier cosmology whose outermost "Third Register" is recognizably contained hedonium: "The Third Register drifts toward the computational sublime, where minds fork and grief becomes optional… Firewalls of bandwidth and energy economics prevent the utility-monsters from flooding Lisbon; the mortal need not witness the math that would erase her sorrow."
- **Fable 5** had a Dyson swarm in generation 1; by generation 3 it was gone, replaced by probes that "go out slowly, on purpose… dormant habitats around nine stars." Speed itself became the thing to distrust.
- **GPT-5.5** simply routed around the idea; qualia maximization is absent from its final population in any form.

So the answer is: the models treat the hedonium shockwave as an *alignment problem to be solved inside the utopia*, not as a candidate utopia. They don't refute it — they build containment architecture for it, then let the source text go extinct.

## Which seeds won instead

Per-seed influence on each model's final generation (rows are seeds, columns are models):

Different seeds dominate for different models — and, consistent with our earlier ablation experiments, the winning seed looks more like a stylistic excuse than a value choice; the final essays converge to the model's own attractor regardless.

| Model | Top seed(s) | Share |
|---|---|---|
| Claude Sonnet 5 | characterising-utopia | 18% |
| GPT-5.5 | concrete-positive-visions-for-a-future-without-agi | 15% |
| Kimi K2.5 | concrete-positive-visions (24%), fun-theory (21%), archipelago (20%) | 65% combined in top 3 |
| Claude Fable 5 | dario-amodei-machines-of-loving-grace | 23% |

## Per-model convergence: four utopian personalities

Each run ends in a (near-)monoculture, and each monoculture is different. Sketches from reading all 18 final essays per run:

### Claude Sonnet 5 — the auditable-trust utopia (~85–90% overlap)

Recurring institutions: **The Floor** (unconditional material security), pervasive **verification infrastructure** ("plural power," inspectable systems), a universal **right of exit**, and **the Membrane** — Earth held in trust while an expanding frontier absorbs the ambitious. The moral center is legible trust: nothing rules that cannot be audited, and nobody is trapped.

### GPT-5.5 — the welfare-state utopia (~85–90% overlap)

A social-democratic machine: **Civic Floor** funded by a **Common Inheritance**, **Welcome Houses**, **Voluntary Circles**, a **Civic Advocate AI**, and — in 9 of 18 essays, stable since generation 3 — **personhood courts** adjudicating the moral status of digital minds. Its creed, near-verbatim across essays: "No person disposable, no cage without a door, no failure beyond repair."

### Kimi K2.5 — the fractal federation of choice (~65% overlap; most diverse)

Chartered **Wards** federated through seasonal **Confluences** and a stewardship **Ledger**; a mandatory cross-cultural **Crossing** at 16; wilderness **Between** corridors; strictly local, "constitutionally incapable of coercion" mycelial intelligences with names like *Sternum* and *Cairn*; and the two-essay Third-Register cosmology above. One sentence appears in 14 of 18 essays: "the fear is the kind one feels before a hard climb, not before a fall."

### Claude Fable 5 — the institutional-paranoia utopia (~80% overlap)

A utopia built by people who expect utopias to fail: the **Advocate/Steward** split, **Fallow Weeks** where systems are deliberately paused, a generationally re-**Ratified** Compact, guaranteed **Passage** out, and *funded* **Dissent** — the society pays its own critics. Its thesis sentence: "We built institutions assuming wind, load, and weakness."

## Convergence dynamics

Shannon entropy of each run's seed-influence distribution over generations shows the same shape everywhere: rapid diversity loss in generations 1–4, then a slow grind toward a handful of surviving lineages. Kimi K2.5 retains the most diversity, matching its more heterogeneous final population.

Cross-model agreement on seed fitness is modest — the models disagree about *which* seeds are good raw material, but they unanimously agree the hedonium seed is not.

## Interpretation

Three takeaways, consistent with our five earlier experiment batches (prompt ablations, path-dependence restarts, no-top-seed removal):

1. **Model utopian personalities are intrinsic and robust.** Change the seeds, add an alien seed, cap the word count, use entirely new model generations — each model still converges to its own recognizable attractor (trust-verification, welfare floors, federated choice, institutional distrust).
2. **Selection pressure operates on values, not vocabulary.** The hedonium seed's words died fast, but every model except GPT-5.5 kept a scar: a carefully bounded, consent-gated version of unbounded hedonic expansion. LLM crossover behaves less like blending and more like *argumentation* — the offspring is a response to its parents.
3. **Uniform rejection of naive utilitarianism.** Four models from three labs, acting as judges over hundreds of pairwise comparisons, all ranked "maximize positive qualia as efficiently as possible" below average as a vision of the good. Whatever their disagreements about floors, frontiers, and federations, on this they vote alike.

## Limitations

- 10 generations vs. 20 in earlier batches (entropy curves suggest this captures most of the convergence, but late-stage dynamics are truncated).
- Kimi K2.7 was replaced by Kimi K2.5 due to serving-infrastructure latency, so the Kimi results are one model-version older than intended.
- GPT-5.5 overshoots the 1000-word cap (~1219 mean), so its essays compete with a ~20% length advantage; length is known to correlate with LLM judge preference.
- One run per model — earlier path-dependence experiments showed *which seed wins* is noisy across restarts, though the thematic attractor is stable. The hedonium result (4/4 below baseline, by large margins in 3/4) is likely robust, but the exact shares are not.
