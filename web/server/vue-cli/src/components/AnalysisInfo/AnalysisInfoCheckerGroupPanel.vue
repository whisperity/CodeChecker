<template>
  <v-expansion-panel>
    <v-expansion-panel-header
      class="pa-0 px-1 primary--text"
    >
      {{ group }}
    </v-expansion-panel-header>
    <v-expansion-panel-content>
      <analysis-info-checker-rows
        :checkers="checkers"
      />
    </v-expansion-panel-content>
  </v-expansion-panel>
</template>

<script>
import AnalysisInfoCheckerRows from "./AnalysisInfoCheckerRows";

export default {
  name: "AnalysisInfoCheckerGroupPanel",
  components: {
    AnalysisInfoCheckerRows
  },
  props: {
    group: { type: String, required: true },
    checkers: { type: Array, required: true }
  }
};
</script>
