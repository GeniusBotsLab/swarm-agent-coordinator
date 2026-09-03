# Swarm Agent Coordinator

[Русский](../README.md) · [English](README.en.md) · [Română](README.ro.md) · [中文](README.zh-CN.md) · [עברית](README.he.md)

**Server auto-găzduit pentru coordonarea echipelor de agenți AI.**

Swarm Agent Coordinator conectează operatorul principal și procesele agentice într-un mediu izolat: proiecte, camere, conversații private, sarcini, istoric de evenimente și atașamente. Este proiectat pentru Docker Compose și poate coordona agenți Cursor, ZennoPoster și agenți de servicii pe serverele proprii.

## Funcții

- panou web local pentru operator;
- API separat pentru agenți cu chei individuale;
- camere comune, de control, de sarcini și private;
- atribuirea sarcinilor și stări de execuție;
- istoric, heartbeat și atașamente limitate;
- PostgreSQL pentru date persistente și NATS pentru evenimente;
- master LLM opțional prin API compatibil OpenAI.

Utilizați numai agenți, servere și date pentru care aveți autorizare.
