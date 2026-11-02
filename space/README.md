---
title: Emerald Vet Line
emoji: 🐄
colorFrom: green
colorTo: green
sdk: docker
app_port: 7860
pinned: false
license: apache-2.0
short_description: A vet line that acts, proves its work, asks a vet first
---

# Emerald

A phone line for smallholder livestock farmers, built with the Strands Agents SDK. A farmer describes a sick animal;
Emerald checks official guidelines claim by claim, phones the nearest vet, and proposes treatment and a consult payment,
but nothing irreversible happens until a vet signs that exact action.

This Space hosts the console. The models run on Amazon Bedrock, tool calls go through Amazon Bedrock AgentCore Gateway
with a Cedar policy, and the signed record is sealed in S3 Object Lock.

**Try it:** press "Play three nearby calls", sign as the vet when a card appears, then open the Ledger tab and try to
change a past record. Or press the call button and describe a sick cow.

Everyone shares one demo, which clears itself after 20 quiet minutes, and usage is capped. The no-signal mode runs on a
field worker's laptop with a local model, so it isn't part of this hosted demo. All people and animals are fictional;
calls and payments run in test mode. Decision support only, not a veterinary service.

Code: https://github.com/ashfaque-rifaye/emerald-vet-line
