// jshint esversion: 6
/* rc slider https://www.npmjs.com/package/rc-slider */

import React from "react";
import _ from "lodash";
import fuzzysort from "fuzzysort";
import { connect } from "react-redux";
import { Suggest } from "@blueprintjs/select";
import {
  MenuItem,
  Button,
  FormGroup,
  InputGroup,
  ControlGroup
} from "@blueprintjs/core";
import HistogramBrush from "../brushableHistogram";
import * as globals from "../../globals";
import actions from "../../actions";
import {
  postUserErrorToast,
  keepAroundErrorToast
} from "../framework/toasters";
import GeneSet from "./geneSet";

import { memoize } from "../../util/dataframe/util";
import testGeneSets from "./test_data";

const renderGene = (fuzzySortResult, { handleClick, modifiers }) => {
  if (!modifiers.matchesPredicate) {
    return null;
  }
  /* the fuzzysort wraps the object with other properties, like a score */
  const geneName = fuzzySortResult.target;

  return (
    <MenuItem
      active={modifiers.active}
      disabled={modifiers.disabled}
      data-testid={`suggest-menu-item-${geneName}`}
      // Use of annotations in this way is incorrect and dataset specific.
      // See https://github.com/chanzuckerberg/cellxgene/issues/483
      // label={gene.n_counts}
      key={geneName}
      onClick={g =>
        /* this fires when user clicks a menu item */
        handleClick(g)
      }
      text={geneName}
    />
  );
};

const filterGenes = (query, genes) =>
  /* fires on load, once, and then for each character typed into the input */
  fuzzysort.go(query, genes, {
    limit: 5,
    threshold: -10000 // don't return bad results
  });

@connect(state => {
  return {
    obsAnnotations: state.world?.obsAnnotations,
    userDefinedGenes: state.controls.userDefinedGenes,
    userDefinedGenesLoading: state.controls.userDefinedGenesLoading,
    world: state.world,
    colorAccessor: state.colors.colorAccessor,
    differential: state.differential
  };
})
class GeneExpression extends React.Component {
  constructor(props) {
    super(props);
    this.state = {
      bulkAdd: "",
      tab: "autosuggest",
      activeItem: null
    };
  }

  _genesToUpper = listGenes => {
    // Has to be a Map to preserve index
    const upperGenes = new Map();
    for (let i = 0, { length } = listGenes; i < length; i += 1) {
      upperGenes.set(listGenes[i].toUpperCase(), i);
    }

    return upperGenes;
  };

  // eslint-disable-next-line react/sort-comp
  _memoGenesToUpper = memoize(this._genesToUpper, arr => arr);

  handleBulkAddClick = () => {
    const { world, dispatch, userDefinedGenes } = this.props;
    const varIndexName = world.schema.annotations.var.index;
    const { bulkAdd } = this.state;

    /*
      test:
      Apod,,, Cd74,,    ,,,    Foo,    Bar-2,,
    */
    if (bulkAdd !== "") {
      const genes = _.pull(_.uniq(bulkAdd.split(/[ ,]+/)), "");
      if (genes.length === 0) {
        return keepAroundErrorToast("Must enter a gene name.");
      }
      const worldGenes = world.varAnnotations.col(varIndexName).asArray();

      // These gene lists are unique enough where memoization is useless
      const upperGenes = this._genesToUpper(genes);
      const upperUserDefinedGenes = this._genesToUpper(userDefinedGenes);

      const upperWorldGenes = this._memoGenesToUpper(worldGenes);

      dispatch({ type: "bulk user defined gene start" });

      Promise.all(
        [...upperGenes.keys()].map(upperGene => {
          if (upperUserDefinedGenes.get(upperGene) !== undefined) {
            return keepAroundErrorToast("That gene already exists");
          }

          const indexOfGene = upperWorldGenes.get(upperGene);

          if (indexOfGene === undefined) {
            return keepAroundErrorToast(
              `${
                genes[upperGenes.get(upperGene)]
              } doesn't appear to be a valid gene name.`
            );
          }
          return dispatch(
            actions.requestUserDefinedGene(worldGenes[indexOfGene])
          );
        })
      ).then(
        () => dispatch({ type: "bulk user defined gene complete" }),
        () => dispatch({ type: "bulk user defined gene error" })
      );
    }

    this.setState({ bulkAdd: "" });
    return undefined;
  };

  renderTestGeneSets = () => {
    const sets = [];

    _.forEach(testGeneSets, (setGenes, setName) => {
      sets.push(
        <GeneSet key={setName} setGenes={setGenes} setName={setName} />
      );
    });

    return sets;
  };

  placeholderGeneNames() {
    /*
    return a string containing gene name suggestions for use as a user hint.
    Eg.,    Apod, Cd74, ...
    Will return a max of 3 genes, totalling 15 characters in length.
    Randomly selects gene names.

    NOTE: the random selection means it will re-render constantly.
    */
    const { world } = this.props;
    const { varAnnotations } = world;
    const varIndexName = world.schema.annotations.var.index;
    const geneNames = varAnnotations.col(varIndexName).asArray();
    if (geneNames.length > 0) {
      const placeholder = [];
      let len = geneNames.length;
      const maxGeneNameCount = 3;
      const maxStrLength = 15;
      len = len < maxGeneNameCount ? len : maxGeneNameCount;
      for (let i = 0, strLen = 0; i < len && strLen < maxStrLength; i += 1) {
        const deal = Math.floor(Math.random() * geneNames.length);
        const geneName = geneNames[deal];
        placeholder.push(geneName);
        strLen += geneName.length + 2; // '2' is the length of a comma and space
      }
      placeholder.push("...");
      return placeholder.join(", ");
    }
    // default - should never happen.
    return "Apod, Cd74, ...";
  }

  handleClick(g) {
    const { world, dispatch, userDefinedGenes } = this.props;
    const varIndexName = world.schema.annotations.var.index;
    if (!g) return;
    const gene = g.target;
    if (userDefinedGenes.indexOf(gene) !== -1) {
      postUserErrorToast("That gene already exists");
    } else if (userDefinedGenes.length > 15) {
      postUserErrorToast(
        "That's too many genes, you can have at most 15 user defined genes"
      );
    } else if (
      world.varAnnotations.col(varIndexName).indexOf(gene) === undefined
    ) {
      postUserErrorToast("That doesn't appear to be a valid gene name.");
    } else {
      dispatch({ type: "single user defined gene start" });
      dispatch(actions.requestUserDefinedGene(gene)).then(
        () => dispatch({ type: "single user defined gene complete" }),
        () => dispatch({ type: "single user defined gene error" })
      );
    }
  }

  render() {
    const {
      world,
      userDefinedGenes,
      userDefinedGenesLoading,
      differential
    } = this.props;
    const varIndexName = world?.schema?.annotations?.var?.index;
    const { tab, bulkAdd, activeItem } = this.state;

    return (
      <div>
        <div>
          <div
            style={{
              padding: globals.leftSidebarSectionPadding
            }}
          >
            <Button
              active={tab === "autosuggest"}
              style={{ marginRight: 5 }}
              minimal
              small
              data-testid="tab-autosuggest"
              onClick={() => {
                this.setState({ tab: "autosuggest" });
              }}
            >
              Autosuggest genes
            </Button>
            <Button
              active={tab === "bulkadd"}
              minimal
              small
              data-testid="section-bulk-add"
              onClick={() => {
                this.setState({ tab: "bulkadd" });
              }}
            >
              Bulk add genes
            </Button>
          </div>

          {tab === "autosuggest" ? (
            <ControlGroup
              style={{
                paddingLeft: globals.leftSidebarSectionPadding,
                paddingBottom: globals.leftSidebarSectionPadding
              }}
            >
              <Suggest
                resetOnSelect
                closeOnSelect
                resetOnClose
                itemDisabled={
                  userDefinedGenesLoading ? () => true : () => false
                }
                noResults={<MenuItem disabled text="No matching genes." />}
                onItemSelect={g => {
                  /* this happens on 'enter' */
                  this.handleClick(g);
                }}
                initialContent={<MenuItem disabled text="Enter a gene…" />}
                inputProps={{ "data-testid": "gene-search" }}
                inputValueRenderer={() => {
                  return "";
                }}
                itemListPredicate={filterGenes}
                onActiveItemChange={item => this.setState({ activeItem: item })}
                itemRenderer={renderGene.bind(this)}
                items={
                  world && world.varAnnotations
                    ? world.varAnnotations.col(varIndexName).asArray()
                    : ["No genes"]
                }
                popoverProps={{ minimal: true }}
              />
              <Button
                className="bp3-button bp3-intent-primary"
                data-testid="add-gene"
                loading={userDefinedGenesLoading}
                onClick={() => this.handleClick(activeItem)}
              >
                Add gene
              </Button>
            </ControlGroup>
          ) : null}
          {tab === "bulkadd" ? (
            <div style={{ paddingLeft: globals.leftSidebarSectionPadding }}>
              <form
                onSubmit={e => {
                  e.preventDefault();
                  this.handleBulkAddClick();
                }}
              >
                <FormGroup
                  helperText="Add a list of genes (comma delimited)"
                  labelFor="text-input-bulk-add"
                >
                  <ControlGroup>
                    <InputGroup
                      onChange={e => {
                        this.setState({ bulkAdd: e.target.value });
                      }}
                      id="text-input-bulk-add"
                      data-testid="input-bulk-add"
                      placeholder={this.placeholderGeneNames()}
                      value={bulkAdd}
                    />
                    <Button
                      intent="primary"
                      onClick={this.handleBulkAddClick}
                      loading={userDefinedGenesLoading}
                    >
                      Add genes
                    </Button>
                  </ControlGroup>
                </FormGroup>
              </form>
            </div>
          ) : null}
          {world && userDefinedGenes.length > 0
            ? _.map(userDefinedGenes, (geneName, index) => {
                const values = world.varData.col(geneName);
                if (!values) {
                  return null;
                }
                const summary = values.summarize();
                return (
                  <HistogramBrush
                    key={geneName}
                    field={geneName}
                    zebra={index % 2 === 0}
                    ranges={summary}
                    isUserDefined
                  />
                );
              })
            : null}
        </div>
        <div>
          {differential.diffExp
            ? _.map(differential.diffExp, (value, index) => {
                const name = world.varAnnotations.at(value[0], varIndexName);
                const values = world.varData.col(name);
                if (!values) {
                  return null;
                }
                const summary = values.summarize();
                return (
                  <HistogramBrush
                    key={name}
                    field={name}
                    zebra={index % 2 === 0}
                    ranges={summary}
                    isDiffExp
                    logFoldChange={value[1]}
                    pval={value[2]}
                    pvalAdj={value[3]}
                  />
                );
              })
            : null}
        </div>
        <div>{this.renderTestGeneSets()}</div>
      </div>
    );
  }
}

export default GeneExpression;
