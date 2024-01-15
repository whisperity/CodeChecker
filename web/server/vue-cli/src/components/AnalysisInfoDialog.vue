<template>
  <v-dialog
    v-model="dialog"
    content-class="analysis-info"
    max-width="80%"
    scrollable
  >
    <v-card>
      <v-card-title
        class="headline primary white--text"
        primary-title
      >
        Analysis information

        <v-spacer />

        <v-btn icon dark @click="dialog = false">
          <v-icon>mdi-close</v-icon>
        </v-btn>
      </v-card-title>

      <v-card-text>
        <v-container class="pa-0 pt-2">
          <!-- eslint-disable vue/no-v-html -->
          <div
            v-for="cmd in analysisInfo.cmds"
            :key="cmd"
            class="analysis-info mb-2"
            v-html="cmd"
          />
        </v-container>

        <v-container class="pa-0 pt-1">
          <v-expansion-panels
            v-model="activeAnalyzerExpansionPanels"
            multiple
            hover
          >
            <v-expansion-panel
              v-for="analyzer in analysisInfo.analyzerNames"
              :key="analyzer"
            >
              <v-expansion-panel-header
                class="pa-0 px-1 primary--text font-weight-black"
              >
                {{ analyzer }}
              </v-expansion-panel-header>

              <v-expansion-panel-content
                class="pa-1"
              >
                <v-container
                  class="checker-columns"
                >
                  <v-row
                    v-for="(checker, idx) in
                      analysisInfo.checkerStatusPerAnalyzer[analyzer]"
                    :key="idx"
                    no-gutters
                  >
                    <v-col
                      cols="auto"
                    >
                      <analyzer-statistics-icon
                        class="mr-2"
                        :value="checker[1]"
                      />
                    </v-col>
                    <v-col
                      class="pr-1"
                    >
                      {{ checker[0] }}
                    </v-col>
                  </v-row>
                </v-container>
              </v-expansion-panel-content>
            </v-expansion-panel>
          </v-expansion-panels>
        </v-container>
      </v-card-text>
    </v-card>
  </v-dialog>
</template>

<script>
import { ccService, handleThriftError } from "@cc-api";
import { AnalyzerStatisticsIcon } from "@/components/Icons";
import { AnalysisInfoFilter } from "@cc/report-server-types";

export default {
  name: "AnalysisInfoDialog",
  components: {
    AnalyzerStatisticsIcon
  },
  props: {
    value: { type: Boolean, default: false },
    runId: { type: Object, default: () => null },
    runHistoryId: { type: Object, default: () => null },
    reportId: { type: Object, default: () => null },
  },

  data() {
    return {
      analysisInfo: {
        cmds: [],
        analyzerNames: [],
        checkerStatusPerAnalyzer: {}
      },
      activeAnalyzerExpansionPanels: [],
      enabledCheckerRgx: new RegExp("^(--enable|-e[= ]*)", "i"),
      disabledCheckerRgx: new RegExp("^(--disable|-d[= ]*)", "i"),
    };
  },

  computed: {
    dialog: {
      get() {
        return this.value;
      },
      set(val) {
        this.$emit("update:value", val);
      }
    },
    analysisInfoCheckers(analyzer) {
      const checkers = this.analysisInfo.checkers[analyzer];
      if (!checkers) {
        return [];
      }
      return Object.keys(checkers).
        sort((a, b) => a.localeCompare(b)).
        map(k => [ k, checkers[k] ]);
    }
  },

  watch: {
    runId() {
      this.getAnalysisInfo();
    },
    runHistoryId() {
      this.getAnalysisInfo();
    },
    reportId() {
      this.getAnalysisInfo();
    }
  },

  mounted() {
    this.getAnalysisInfo();
  },

  methods: {
    getAnalyzersSorted() {
      return Object.keys(this.analysisInfo.checkers).sort((a, b) =>
        a.localeCompare(b));
    },

    highlightOptions(cmd) {
      return cmd.split(" ").map(param => {
        if (!param.startsWith("-")) {
          return param;
        }

        const classNames = [ "param" ];
        if (this.enabledCheckerRgx.test(param)) {
          classNames.push("enabled-checkers");
        } else if (this.disabledCheckerRgx.test(param)) {
          classNames.push("disabled-checkers");
        } else if (param.startsWith("--ctu")) {
          classNames.push("ctu");
        } else if (param.startsWith("--stats")) {
          classNames.push("statistics");
        }

        return `<span class="${classNames.join(" ")}">${param}</span>`;
      }).join(" ").replace(/(?:\r\n|\r|\n)/g, "<br>");
    },

    reduceCheckerStatuses(accumulator, newInfo) {
      for (const [ analyzer, checkers ] of Object.entries(newInfo)) {
        if (!accumulator[analyzer]) {
          accumulator[analyzer] = {};
        }
        for (const [ checker, checkerInfo ] of Object.entries(checkers)) {
          accumulator[analyzer][checker] =
            accumulator[analyzer][checker] || checkerInfo.enabled;
        }
      }

      return accumulator;
    },

    storeSortedViewData(checkerStatuses) {
      this.analysisInfo.analyzerNames = Object.keys(checkerStatuses).sort();
      this.analysisInfo.checkerStatusPerAnalyzer =
        Object.fromEntries(Object.keys(checkerStatuses).map(
          analyzer => [ analyzer,
            Object.keys(checkerStatuses[analyzer]).sort().map(
              checker => [ checker,
                (checkerStatuses[analyzer][checker]) ? "successful" : "failed"
              ]
            )
          ]
        ));

      this.activeAnalyzerExpansionPanels = [ ...Array(
        Object.keys(checkerStatuses).length).keys() ];
      console.log(this.activeAnalyzerExpansionPanels);
    },

    getAnalysisInfo() {
      if (
        !this.dialog ||
        (!this.runId && !this.runHistoryId && !this.reportId)
      ) {
        return;
      }

      const analysisInfoFilter = new AnalysisInfoFilter({
        runId: this.runId,
        runHistoryId: this.runHistoryId,
        reportId: this.reportId,
      });

      const limit = null;
      const offset = 0;
      ccService.getClient().getAnalysisInfo(analysisInfoFilter, limit,
        offset, handleThriftError(analysisInfo => {
          this.analysisInfo.cmds = analysisInfo.map(ai =>
            this.highlightOptions(ai.analyzerCommand));

          const checkerStatuses = analysisInfo.map(ai => ai.checkers).
            reduce(this.reduceCheckerStatuses, {});
          this.storeSortedViewData(checkerStatuses);
        }));
    }
  }
};
</script>

<style lang="scss" scoped>
::v-deep .analysis-info {
  border: 1px solid grey;
  padding: 4px;

  .param {
    background-color: rgba(0, 0, 0, 0.15);
    font-weight: bold;
    padding-left: 2px;
    padding-right: 2px;
  }

  .enabled-checkers {
    background-color: rgba(0, 142, 0, 0.15);
  }

  .disabled-checkers {
    background-color: rgba(142, 0, 0, 0.15);
  }

  .ctu, .statistics {
    background-color: rgba(0, 0, 142, 0.15);
  }

  .checker-columns {
    columns: 32em auto;
  }
}
</style>
