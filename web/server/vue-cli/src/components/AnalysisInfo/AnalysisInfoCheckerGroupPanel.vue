<template>
  <v-expansion-panel>
    <v-expansion-panel-header
      class="pa-0 px-1 primary--text"
    >
      <v-row
        no-gutters
        align="center"
      >
        <v-col cols="auto">
          <v-chip
            v-if="!needDetailedCounts"
            class="mr-1"
            :color="groupWideStatus"
            :ripple="false"
            outlined
            dark
            small
          >
            <v-icon
              v-if="groupWideStatus === 'success'"
              start
            >
              mdi-check
            </v-icon>
            <v-icon
              v-else-if="groupWideStatus === 'error'"
              start
            >
              mdi-close
            </v-icon>
          </v-chip>
        </v-col>
        <v-col cols="auto">
          {{ group }}
        </v-col>
        <v-col cols="auto">
          <count-chips
            v-if="needDetailedCounts"
            :num-good="counts[0]"
            :num-bad="counts[1]"
            :num-total="counts[2]"
            :simplify-showing-if-all="true"
            :show-total="true"
            :show-dividers="false"
            :show-zero-chips="false"
            class="pl-2"
          />
        </v-col>
      </v-row>
    </v-expansion-panel-header>
    <v-expansion-panel-content>
      <analysis-info-checker-rows
        :checkers="checkers"
      />
    </v-expansion-panel-content>
  </v-expansion-panel>
</template>

<script>
import CountChips from "@/components/CountChips";
import AnalysisInfoCheckerRows from "./AnalysisInfoCheckerRows";

export default {
  name: "AnalysisInfoCheckerGroupPanel",
  components: {
    AnalysisInfoCheckerRows,
    CountChips,
  },
  props: {
    group: { type: String, required: true },
    checkers: { type: Array, required: true },
    counts: { type: Array, required: true }
  },
  computed: {
    needDetailedCounts() {
      return this.counts[0] > 0 && this.counts[1] > 0;
    },
    groupWideStatus() {
      if (this.counts[0] > 0 && this.counts[1] === 0)
        return "success";
      if (this.counts[0] === 0 && this.counts[1] > 0)
        return "error";
      return "indeterminate";
    }
  }
};
</script>
