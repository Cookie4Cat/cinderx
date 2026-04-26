# Benchmarks

官方 2/3/4 月优化里 benchmark 是很重要的一层。它不是附属品，而是帮助判断 optimization hypothesis 是否成立的工具。

## 重点 commits

- `6e5e3716` Add three more CinderX benchmarks
- fastmark benchmark support series
- JIT compile speed benchmark series

## Workload coverage

| benchmark | 关注点 |
| --- | --- |
| `nbody` | numeric loop、float operation、unbox |
| `spectral_norm` | numeric loop、call overhead、float path |
| `binary-trees` | allocation、object lifetime、refcount |
| `richards` | attribute / method / object dispatch |
| `deltablue` | global rebound、attribute access、planner state |
| `regex_compile` | mixed integer / compact long / container logic |
| `fannkuch` | tight loop、integer path |
| `fastmark` | JIT compile throughput / codegen overhead |

## 可复用方法

- microbench 用来证明机制。
- selected pyperformance 用来证明没有明显副作用。
- full pyperformance 或 repeated selected run 用来判断是否值得继续。
- negative result 也要记录，尤其是看起来合理但 benchmark 不支持的 fast path。
