/**
 * Where the chart library is loaded from. It is a separate object so a test can swap in a
 * stand in: the real charts draw on a canvas, which the test browser does not have.
 */
export const runtime = {
  load: () => import('@/analytics/echarts-setup'),
}
