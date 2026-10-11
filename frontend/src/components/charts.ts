import {
  BarController,
  BarElement,
  BubbleController,
  CategoryScale,
  Chart,
  Filler,
  Legend,
  LinearScale,
  LineController,
  LineElement,
  PointElement,
  Tooltip,
} from "chart.js";

// Register only what we use (keeps the bundle smaller than `chart.js/auto`).
Chart.register(BarController, BarElement, BubbleController, CategoryScale, Filler, Legend, LinearScale, LineController, LineElement, PointElement, Tooltip);

Chart.defaults.font.family = "'Archivo Variable', system-ui, sans-serif";
Chart.defaults.font.size = 12;
Chart.defaults.color = "#5b6878";
Chart.defaults.borderColor = "#e3e8ee";
Chart.defaults.plugins.tooltip.backgroundColor = "#1b2430";
Chart.defaults.plugins.tooltip.padding = 10;
Chart.defaults.plugins.tooltip.cornerRadius = 4;
Chart.defaults.plugins.legend.labels.boxWidth = 14;
Chart.defaults.plugins.legend.labels.boxHeight = 4;

export const COLORS = {
  ink: "#1b2430",
  heat: "#c53030",
  heatSoft: "rgba(197, 48, 48, 0.78)",
  rain: "#2b6cb0",
  rainSoft: "rgba(43, 108, 176, 0.75)",
  trend: "#2b6cb0",
  muted: "#9aa5b1",
};
