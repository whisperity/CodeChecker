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
            multiple
            hover
          >
            <v-expansion-panel
              v-for="analyzer in analysisInfo.analyzers"
              :key="analyzer"
            >
              <v-expansion-panel-header
                class="pa-0 px-1"
              >
                <v-row
                  no-gutters
                  align="center"
                >
                  <v-col
                    cols="auto"
                    class="pa-1 analyzer-name primary--text"
                  >
                    {{ analyzer }}
                  </v-col>
                  <v-col cols="auto">
                    <count-chips
                      :num-good="analysisInfo.counts[analyzer]
                        [groupMeta.AnalyzerTotal][countMeta.Enabled]"
                      :num-bad="analysisInfo.counts[analyzer]
                        [groupMeta.AnalyzerTotal][countMeta.Disabled]"
                      :num-total="analysisInfo.counts[analyzer]
                        [groupMeta.AnalyzerTotal][countMeta.Total]"
                      :good-text="'Number of checkers enabled (executed)'"
                      :bad-text="'Number of checkers disabled (not executed)'"
                      :total-text="'Number of checkers available'"
                      :simplify-showing-if-all="true"
                      :show-total="true"
                      :show-dividers="false"
                      :show-zero-chips="false"
                      class="pl-2"
                    />
                  </v-col>
                </v-row>
              </v-expansion-panel-header>

              <v-expansion-panel-content
                class="pa-1"
              >
                <template
                  v-for="(checkers, group) in analysisInfo.checkers[analyzer]"
                >
                  <analysis-info-checker-group-panel
                    v-if="group !== groupMeta.NoGroup"
                    :key="group"
                    :group="group"
                    :checkers="checkers"
                    :counts="analysisInfo.counts[analyzer][group]"
                  />
                  <analysis-info-checker-rows
                    v-else
                    :key="group"
                    :checkers="checkers"
                  />
                </template>
              </v-expansion-panel-content>
            </v-expansion-panel>
          </v-expansion-panels>
        </v-container>
      </v-card-text>
    </v-card>
  </v-dialog>
</template>

<script>
import {
  AnalysisInfoCheckerGroupPanel,
  AnalysisInfoCheckerRows
} from "@/components/AnalysisInfo";
import CountChips from "@/components/CountChips";
import { ccService, handleThriftError } from "@cc-api";
import { AnalysisInfoFilter } from "@cc/report-server-types";

const GroupMeta = Object.freeze({ NoGroup: "__N", AnalyzerTotal: "__S" });
const CountMeta = Object.freeze({ Enabled: 0, Disabled: 1, Total: 2 });

export default {
  name: "AnalysisInfoDialog",
  components: {
    AnalysisInfoCheckerGroupPanel,
    AnalysisInfoCheckerRows,
    CountChips
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
        analyzers: [],
        checkers: {},
        checkerCounts: {}
      },
      enabledCheckerRgx: new RegExp("^(--enable|-e[= ]*)", "i"),
      disabledCheckerRgx: new RegExp("^(--disable|-d[= ]*)", "i")
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
    groupMeta() {
      return GroupMeta;
    },
    countMeta() {
      return CountMeta;
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

    getTopLevelCheckGroup(analyzerName, checkerName) {
      const clangTidyClangDiagnostic = checkerName.split("clang-diagnostic-");
      if (clangTidyClangDiagnostic.length > 1 &&
        clangTidyClangDiagnostic[0] === "")
      {
        // Unfortunately, this is historically special...
        return "clang-diagnostic";
      }

      const splitDot = checkerName.split(".");
      if (splitDot.length > 1) {
        return splitDot[0];
      }

      const splitHyphen = checkerName.split("-");
      if (splitHyphen.length > 1) {
        if (splitHyphen[0] === analyzerName) {
          // cppcheck-PointerSize -> <NoGroup>
          // gcc-fd-leak          -> "fd"
          return splitHyphen.length >= 3 ? splitHyphen[1] : GroupMeta.NoGroup;
        }
        // bugprone-easily-swappable-parameters -> "bugprone"
        return splitHyphen[0];
      }

      return GroupMeta.NoGroup;
    },

    reduceCheckerStatuses(accumulator, newInfo) {
      for (const [ analyzer, checkers ] of Object.entries(newInfo)) {
        if (!accumulator[analyzer]) {
          accumulator[analyzer] = {};
          accumulator[analyzer][GroupMeta.NoGroup] = {};
        }
        for (const [ checker, checkerInfo ] of Object.entries(checkers)) {
          const group = this.getTopLevelCheckGroup(analyzer, checker);
          if (!accumulator[analyzer][group]) {
            accumulator[analyzer][group] = {};
          }
          accumulator[analyzer][group][checker] =
            accumulator[analyzer][group][checker] || checkerInfo.enabled;
        }
      }

      return accumulator;
    },

    sortAndStoreCheckerInfo(checkerStatuses) {
      this.analysisInfo.analyzers = Object.keys(checkerStatuses).sort();
      this.analysisInfo.checkers =
        Object.fromEntries(Object.keys(checkerStatuses).map(
          analyzer => [ analyzer,
            Object.fromEntries(
              Object.keys(checkerStatuses[analyzer]).sort().map(
                group => [ group,
                  Object.keys(checkerStatuses[analyzer][group]).sort().map(
                    checker => [ checker,
                      checkerStatuses[analyzer][group][checker]
                    ])
                ])
            )
          ]));

      this.analysisInfo.counts =
        Object.fromEntries(Object.keys(checkerStatuses).map(
          analyzer => [ analyzer,
            Object.fromEntries(
              Object.keys(checkerStatuses[analyzer]).map(
                group => [ group,
                  [
                    // [0]: #[Enabled checkers]
                    Object.keys(checkerStatuses[analyzer][group])
                      .map(checker =>
                        checkerStatuses[analyzer][group][checker] ? 1 : 0)
                      .reduce((a, b) => a + b, 0),
                    // [1]: #[Disabled checkers] (Note: will be updated later)
                    -1,
                    // [2]: #[Total checkers]
                    Object.keys(checkerStatuses[analyzer][group]).length
                  ]
                ]))
          ]));
      const counts = this.analysisInfo.counts;
      Object.keys(counts).map(
        analyzer => Object.keys(counts[analyzer]).map(
          group => {
            counts[analyzer][group][CountMeta.Disabled] =
              counts[analyzer][group][CountMeta.Total] -
              counts[analyzer][group][CountMeta.Enabled];
          }));
      Object.keys(counts).map(
        analyzer => {
          const sum = Object.values(counts[analyzer])
            .reduce((as, bs) => [
              as[CountMeta.Enabled]  + bs[CountMeta.Enabled],
              as[CountMeta.Disabled] + bs[CountMeta.Disabled],
              as[CountMeta.Total]    + bs[CountMeta.Total],
            ]);
          counts[analyzer][GroupMeta.AnalyzerTotal] = sum;
        });
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
          if (!Object.keys(checkerStatuses).length) {
            this.sortAndStoreCheckerInfo({}); // Reset.
            console.warn("No result!");
          } else {
            this.sortAndStoreCheckerInfo(checkerStatuses);
          }
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

  .analyzer-name {
    font-size: 125%;
    font-weight: bold;
  }
}
</style>
