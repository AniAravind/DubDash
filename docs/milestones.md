# One-month demonstration plan

1. **Week 1 — camera and people:** integrate capture; calibrate stereo; record a
   repeatable route; run the person detector; record image age and inference latency.
2. **Week 2 — geometry and stopping:** compare depth against tape measurements at
   multiple ranges, lighting conditions and speeds. Implement ground filtering,
   unknown-space handling and a health supervisor; measure end-to-end stopping.
3. **Week 3 — localization:** validate wheel odometry independently, then visual
   odometry. Save a route map; test relocalization and optional sensor fusion.
4. **Week 4 — supervised deliveries:** integrate Nav2 and Collision Monitor,
   perform perception-loss tests, and rehearse one mapped route repeatedly.

Record trial conditions, timestamp skew, valid depth coverage, distance error,
localization drift, latency and stopping distance. Define acceptance thresholds
from robot speed, braking performance and route geometry before enabling motion.
If moving stereo is unreliable, change the camera before expanding autonomy.
