import {
  ADD_CHAIN, REMOVE_CHAIN, UPDATE_CHAIN, ADD_NODE, ADD_REPOSITORY,
} from './types';

export function addChain(payload) {
  return {
    type: ADD_CHAIN,
    payload,
  };
}

export function removeChain(payload) {
  return {
    type: REMOVE_CHAIN,
    payload,
  };
}

export function updateChain(payload) {
  return {
    type: UPDATE_CHAIN,
    payload,
  };
}

export function addNode(payload) {
  return {
    type: ADD_NODE,
    payload,
  };
}

export function addRepository(payload) {
  return {
    type: ADD_REPOSITORY,
    payload,
  };
}
