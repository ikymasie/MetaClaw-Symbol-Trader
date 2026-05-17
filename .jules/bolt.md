## 2026-05-17 - [Pandas Iteration Overhead]
**Learning:** df.iterrows() is a significant bottleneck in this application and should be avoided due to Pandas Series boxing overhead.
**Action:** Use zip() over columns for parallel traversal, or df.to_dict('records') for row-based dictionaries to improve iteration performance.
