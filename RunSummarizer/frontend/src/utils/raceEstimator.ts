/**
 * Pete Riegel's endurance prediction formula:
 * T2 = T1 * (D2 / D1)^1.06
 *
 * D1: base distance in meters
 * T1: base time in seconds
 * D2: target distance in meters
 * T2: predicted time in seconds
 */

export interface RacePredictions {
  fiveK: number;
  tenK: number;
  halfMarathon: number;
  marathon: number;
}

const RIEGEL_EXPONENT = 1.06;

export const TARGET_DISTANCES = {
  fiveK: 5000,
  tenK: 10000,
  halfMarathon: 21097.5,
  marathon: 42195,
} as const;

export const estimateRaceTimes = (
  distanceMeters: number,
  durationSeconds: number
): RacePredictions | null => {
  if (distanceMeters <= 500 || durationSeconds <= 60) {
    return null;
  }

  const predict = (targetMeters: number): number => {
    return Math.round(
      durationSeconds * Math.pow(targetMeters / distanceMeters, RIEGEL_EXPONENT)
    );
  };

  return {
    fiveK: predict(TARGET_DISTANCES.fiveK),
    tenK: predict(TARGET_DISTANCES.tenK),
    halfMarathon: predict(TARGET_DISTANCES.halfMarathon),
    marathon: predict(TARGET_DISTANCES.marathon),
  };
};
