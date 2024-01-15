<template>
  <v-row
    no-gutters
    align="center"
  >
    <v-col
      cols="auto"
    >
      <analyzer-statistics-icon
        class="mr-2"
        :value="(enabled ? 'successful' : 'failed')"
      />
    </v-col>
    <v-col
      class="pr-1"
    >
      {{ name }}
    </v-col>
  </v-row>
</template>

<script>
import { AnalyzerStatisticsIcon } from "@/components/Icons";

export default {
  name: "AnalysisInfoCheckerRow",
  components: {
    AnalyzerStatisticsIcon
  },
  props: {
    enabled: { type: Boolean, required: true },
    name: { type: String, required: true }
  }
};
</script>
