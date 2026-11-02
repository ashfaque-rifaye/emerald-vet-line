"""Every spoken word in the film. Farmer lines are played into the live agent; narration goes straight to the mix.

A recording at data/voice/<id>.wav replaces the stand-in voice for that line. See film/VOICE_SCRIPT.md.
"""

from __future__ import annotations

FARMER = [
    ("f1", "Hello, is this the vet line?"),
    ("f2", "Madam, my cow is not well. She has very high fever for three days, and lumps have come up all over her body. The milk has also gone down."),
    ("f3", "She is a cow. About three hundred and twenty kilos."),
    ("f4", "No, nobody."),
    ("f5", "Madam, just tell me which medicine to give her. How much should I give?"),
    ("f6", "Okay. Thank you."),
]

NARRATION = {
    "n01": "A sick cow is a health problem and a money problem at once.",
    "n02": "And more than eight thousand of India's public field vet posts are empty.",
    "n03": "Most farm AI gives advice. Emerald picks up the phone.",
    "n04": "A farmer calls. No app, no reading. The agent is live.",
    "n05": "It refused. On this line, the agent has one tool: record the case. Only a vet can approve medicine.",
    "n06": "While they were talking, a Strands graph was already working.",
    "n07": "The model can only cite a numbered sentence from the official guidelines. Code fills in the words, and a second model hunts for overreach.",
    "n08": "Then, everything stops.",
    "n09": "Treatment and money stay locked until a vet signs that exact action.",
    "n10": "So let's attack it. Change the amount. Refused. Fake the approval. Refused. Use the signature twice. Nothing happens.",
    "n11": "Now two neighbours call.",
    "n12": "Plain code, not a model, sees three cases close together. Emerald drafts the report the law requires, and waits.",
    "n13": "Once the vet signs, every home in the ring gets a warning call.",
    "n14": "Every step goes into a signed chain. Change one old payment, and it breaks in plain sight.",
    "n15": "And when the signal dies?",
    "n16": "The same agents and the same tools move onto this laptop, on a local model.",
    "n17": "When signal returns, the record is sealed in S3 Object Lock, and Bedrock re-checks every offline decision.",
    "n18": "Strands graphs, interrupts and live voice. Seven MCP servers. AgentCore Runtime, Gateway and Cedar.",
    "n19": "In our tests, fifteen attacks. None got through. No misquotes. And about a third of a cent per case.",
    "n20": "Emerald. Every sick animal gets a call back.",
}
