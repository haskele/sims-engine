import { DK_CONFIG, FD_CONFIG } from './constants';

/**
 * Calculate DraftKings fantasy points from batting stats
 */
export function calcDKBattingPoints(stats) {
  const s = DK_CONFIG.scoring;
  return (
    (stats.singles || 0) * s.single +
    (stats.doubles || 0) * s.double +
    (stats.triples || 0) * s.triple +
    (stats.homeRuns || 0) * s.homeRun +
    (stats.rbi || 0) * s.rbi +
    (stats.runs || 0) * s.run +
    (stats.walks || 0) * s.walk +
    (stats.hbp || 0) * s.hbp +
    (stats.stolenBases || 0) * s.stolenBase +
    (stats.caughtStealing || 0) * s.caughtStealing
  );
}

/**
 * Calculate DraftKings fantasy points from pitching stats
 */
export function calcDKPitchingPoints(stats) {
  const s = DK_CONFIG.scoring;
  return (
    (stats.inningsPitched || 0) * s.inningPitched +
    (stats.strikeouts || 0) * s.strikeout +
    (stats.earnedRuns || 0) * s.earnedRun +
    (stats.hitsAllowed || 0) * s.hit +
    (stats.walksAllowed || 0) * s.walkPitching +
    (stats.hbpAllowed || 0) * s.hbpPitching +
    (stats.win ? s.win : 0) +
    (stats.completeGame ? s.completeGameBonus : 0) +
    (stats.shutout ? s.cgShutoutBonus : 0) +
    (stats.noHitter ? s.noHitterBonus : 0)
  );
}

/**
 * Calculate FanDuel fantasy points from batting stats
 */
export function calcFDBattingPoints(stats) {
  const s = FD_CONFIG.scoring;
  return (
    (stats.singles || 0) * s.single +
    (stats.doubles || 0) * s.double +
    (stats.triples || 0) * s.triple +
    (stats.homeRuns || 0) * s.homeRun +
    (stats.rbi || 0) * s.rbi +
    (stats.runs || 0) * s.run +
    (stats.walks || 0) * s.walk +
    (stats.hbp || 0) * s.hbp +
    (stats.stolenBases || 0) * s.stolenBase +
    (stats.caughtStealing || 0) * s.caughtStealing
  );
}

/**
 * Calculate FanDuel fantasy points from pitching stats
 */
export function calcFDPitchingPoints(stats) {
  const s = FD_CONFIG.scoring;
  return (
    (stats.win ? s.win : 0) +
    (stats.earnedRuns || 0) * s.earnedRun +
    (stats.strikeouts || 0) * s.strikeout +
    (stats.inningsPitched || 0) * s.inningPitched +
    (stats.qualityStart ? s.qualityStart : 0)
  );
}

/**
 * Calculate value (points per $1000 salary)
 */
export function calcValue(projectedPoints, salary) {
  if (!salary || salary === 0) return 0;
  return (projectedPoints / salary) * 1000;
}
