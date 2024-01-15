<template>
  <v-container
    class="analysis-info-checker-rows-in-columns"
  >
    <analysis-info-checker-row
      v-for="(checker, idx) in checkers"
      :key="idx"
      :name="checker[0]"
      :enabled="checker[1]"
    />
  </v-container>
</template>

<script>
import AnalysisInfoCheckerRow from "./AnalysisInfoCheckerRow";

export default {
  name: "AnalysisInfoCheckerRows",
  components: {
    AnalysisInfoCheckerRow
  },
  props: {
    checkers: { type: Array, required: true }
  }
};
</script>

<style lang="scss" scoped>
.analysis-info-checker-rows-in-columns {
  columns: 32em auto;
}
</style>
