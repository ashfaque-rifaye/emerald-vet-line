# Submission kit: Strands SDK: Workshop to Ship

Deadline: treat as **Thu Nov 5, 2026, 12:29 PM IST** (Nov 4, 11:59 PM PDT). A submission missing any part below is not judged.

## Pass/fail checklist

| # | Requirement | Status |
|---|---|---|
| 1 | Complete the Strands workshop within the submission period | **You must do this.** Free sandbox, listed on Builder Center |
| 2 | Agent built with the Strands Agents SDK, for a social good challenge, on AWS | Done. Deployed on AgentCore Runtime |
| 3 | Project article published on Builder Center | Draft: [`ARTICLE.md`](ARTICLE.md). **You publish it** |
| 4 | Public repo with an OSI licence | Done. https://github.com/ashfaque-rifaye/emerald-vet-line (Apache-2.0) |
| 5 | Public video under 3 minutes, on YouTube, Vimeo, Facebook Video or Youku, with no unlicensed music or trademarks | Built, no music. **You upload it** |
| 6 | Original, not previously published | Yes. Never published before this entry |

## Steps for you, in order

1. Open the hackathon page and press **Join**: https://builder.aws.com/build/hackathons/8311dcb5-1ece-3d62-a441-2e1c2ad90b86
2. Request the free sandbox and complete *Building AI Agents with Strands SDK: From Simple Loops to Multi-Agent Swarms*.
3. Upload `emerald-demo.mp4` (the file sent to you, also at `data/video/`) to YouTube as **Public**, with `emerald-demo.srt` as captions. Use the title and description below.
4. Create the article on Builder Center from `docs/ARTICLE.md`. Upload `docs/images/cover.png`, `vet.png`, `ring.png` and `night.png`, and replace VIDEO_LINK with your video's address.
5. Add the video link to the README, where it says "added on upload".
6. Submit the project with the fields below.

## Copy-paste fields

**Project name:** Emerald

**Focus area:** Health

**One line:** A phone line for smallholder livestock farmers that acts on a sick-animal call, proves its reasoning, and gets a vet's signature before anything irreversible.

**Short description:**
Emerald is a voice agent for smallholder livestock farmers, built with the Strands Agents SDK. A farmer describes a sick animal in Hindi. Emerald checks official guidelines claim by claim, phones the nearest vet with the evidence, and proposes treatment and a consult payment, but nothing irreversible happens until a vet signs that exact action. If nearby cases cluster, it drafts the legally required report and, once signed, warns every home around them. With no signal, the same agents and tools run on a laptop. All data is synthetic and it hasn't been used with real farmers. In tests, 0 of 15 attacks got through.

**Repo:** https://github.com/ashfaque-rifaye/emerald-vet-line

**Video title:** Emerald: a vet line that acts, proves its work, and asks a vet first

**Video description:**
Emerald is a phone line for smallholder livestock farmers, built with the Strands Agents SDK and Amazon Bedrock. All footage is from the real running system. The farmer's voice is a synthetic Hindi voice, and all people in the demo are synthetic. Calls and payments are labelled simulations. It has not been used with real farmers, and it is decision support only, not a veterinary service. Code: https://github.com/ashfaque-rifaye/emerald-vet-line

## How this maps to the judging

| Criterion (25% each) | Where to point |
|---|---|
| Social impact | Article's opening and "What I measured". Be plain that field impact isn't proven yet |
| Technical execution | `eval/RESULTS.md`, 68 automated tests, Runtime deployment |
| Communication | The article and the video |
| Originality | Durable cross-person sign-off, proof loop with a custom node, one design in two lanes, Gateway plus Cedar, Object Lock |

## Worth doing if you can

A real vet reviewing even 20 cases, or a 20-second clip of one reacting, would be the biggest credibility gain available.
