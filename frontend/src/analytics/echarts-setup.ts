// Only the chart types the dashboard uses are included, to keep the bundle small. This file is
// loaded on demand, the first time a chart is drawn.
import {
  BarChart,
  FunnelChart,
  GaugeChart,
  HeatmapChart,
  LineChart,
  PieChart,
  RadarChart,
  ScatterChart,
} from 'echarts/charts'
import {
  AriaComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  RadarComponent,
  TitleComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components'
import { init, use as register } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'

register([
  BarChart,
  LineChart,
  PieChart,
  HeatmapChart,
  ScatterChart,
  GaugeChart,
  FunnelChart,
  RadarChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  VisualMapComponent,
  MarkLineComponent,
  RadarComponent,
  TitleComponent,
  AriaComponent,
  CanvasRenderer,
])

export { init }
