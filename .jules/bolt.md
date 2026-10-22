
## 2024-05-18 - [Frontend React Hook O(N) lookup bottleneck]
**Learning:** Using `Object.keys().find()` inside a `.map()` callback during frequent websocket React state updates (`setAgents` in `useAgentStream.ts`) creates a hidden O(N*M) performance drag.
**Action:** Always extract static mapping objects and pre-compute O(1) reverse lookup dictionaries outside the React component/hook to bypass array traversal overhead during fast state renders.
