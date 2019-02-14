import random
from graph_completion.TripleGraph import TripleGraph
from data.reader import read_mapping, read_triples, read_seeds, read_rules
from tools.print_time_info import print_time_info


def _print_result_log(new_triples, language_pair, method, data_name='triple'):
    print('------------------------------------------------------------')
    print_time_info('language_pair: ' + language_pair)
    print_time_info('Method: ' + method)
    for language, new_triple in new_triples.items():
        print_time_info(
            language + ' new %s numbers: ' % data_name + str(len(new_triple)))
    print('------------------------------------------------------------\n')


def _check(ori, new, num):
    if len(ori) != len(new):
        print_time_info('Check failed %d.' % num, print_error=True)
        raise ValueError()


def _load_languge(directory, language):
    triples = read_triples(directory / ('triples_' + language + '.txt'))
    entity2id = read_mapping(directory / ('entity2id_' + language + '.txt'))
    relation2id = read_mapping(
        directory / ('relation2id_' + language + '.txt'))
    rules = read_rules(directory / 'AMIE' /
                       ('rule_for_triples_' + language + '.txt'), relation2id)
    id2entity = {i: entity for entity, i in entity2id.items()}
    id2relation = {i: relation for relation, i in relation2id.items()}
    return triples, id2entity, id2relation, rules


def _load_seeds(directory, train_seeds_ratio):
    relation_seeds = read_seeds(directory / 'relation_seeds.txt')
    entity_seeds = read_seeds(
        directory / 'JAPE' / ('0_' + str(int(10 * train_seeds_ratio))) / 'train_entity_seeds.txt')
    return entity_seeds, relation_seeds


def print_triple(triple, id2entity, id2relation, end='\n'):
    head, tail, relation = triple
    print_time_info(
        ' '.join([id2entity[head], id2relation[relation], id2entity[tail]]), end=end)


def print_rule(rule, id2relation):
    premises, hypothesis, conf = rule
    premises = [(premise[0], id2relation[premise[2]], premise[1])
                for premise in premises]
    hypothesis = [(hypothesis[0], id2relation[hypothesis[2]], hypothesis[1])]
    rule = premises + [['=>']] + hypothesis + [[str(conf)]]
    print_time_info('  '.join(' '.join(part) for part in rule))


def _print_new_rules(bi_new_rules, id2relation_sr, id2relation_tg):
    for language, rules in bi_new_rules.items():
        print_time_info(language, print_error=True)
        for rule in random.choices(rules, k=10):
            if language == 'sr':
                print_rule(rule, id2relation_sr)
            else:
                print_rule(rule, id2relation_tg)


def _print_new_triple_confs(bi_new_triple_confs, id2entity_sr, id2entity_tg, id2relation_sr, id2relation_tg):
    for language, triple_confs in bi_new_triple_confs.items():
        print_time_info(language, print_error=True)
        for triple in random.choices(list(triple_confs.keys()), k=10):
            conf = triple_confs[triple]
            if language == 'sr':
                print_triple(triple, id2entity_sr, id2relation_sr, end='')
            else:
                print_triple(triple, id2entity_tg, id2relation_tg, end='')
            print(' ', conf)


def rule_based_graph_completion(triples_sr, triples_tg, rules_sr, rules_tg):
    '''
    triples = [(head, tail, relation)]
    return new [((head, tail, relation), conf)...]
    '''
    print_time_info('Rule based graph completion started!')

    def _rule_based_graph_completion(triples, rules):
        tg = TripleGraph()
        tg.load(triples)
        triples = set(triples)
        new_triple_confs = {}

        for rule in rules:
            new_triple_conf_candidates = tg.inference_by_rule(rule)
            for new_triple, conf in new_triple_conf_candidates:
                if not new_triple in triples:
                    if new_triple not in new_triple_confs:
                        new_triple_confs[new_triple] = conf
                    else:
                        ori_conf = new_triple_confs[new_triple]
                        new_triple_confs[new_triple] = max(conf, ori_conf)
        return new_triple_confs
    new_triple_confs_sr = _rule_based_graph_completion(triples_sr, rules_sr)
    new_triple_confs_tg = _rule_based_graph_completion(triples_tg, rules_tg)
    print_time_info('Rule based graph completion finished!')
    return triples_sr + list(new_triple_confs_sr.keys()), triples_tg + list(new_triple_confs_tg.keys()), {'sr': new_triple_confs_sr, 'tg': new_triple_confs_tg}


def rule_transfer(rules_sr, rules_tg, relation_seeds):
    '''
    目前仅能处理len(premises) <= 2的情况
    '''
    rule2conf_sr = {(premises, hypothesis): conf for premises,
                    hypothesis, conf in rules_sr}
    rule2conf_tg = {(premises, hypothesis): conf for premises,
                    hypothesis, conf in rules_tg}
    from pprint import pprint

    def _rule_transfer(rule2conf_sr, rule2conf_tg, r2r):
        new_rules = []
        for rule, conf in rule2conf_sr.items():
            premises, hypothesis = rule
            relations = [premise[2] for premise in premises] + [hypothesis[2]]
            feasible = True
            for relation in relations:
                if not relation in r2r:
                    feasible = False
            if feasible:
                premises = tuple([(head, tail, r2r[relation])
                                  for head, tail, relation in premises])
                hypothesis = (hypothesis[0], hypothesis[1], r2r[hypothesis[2]])
                if (premises, hypothesis) not in rule2conf_tg:
                    if len(premises) == 1:
                        new_rules.append((premises, hypothesis, conf))
                    else:
                        premises = (premises[1], premises[0])
                        if premises not in rule2conf_tg:
                            new_rules.append((premises, hypothesis, conf))
        return new_rules

    r2r = dict((relation_sr, relation_tg)
               for relation_sr, relation_tg in relation_seeds)
    new_rules_tg = _rule_transfer(rule2conf_sr, rule2conf_tg, r2r)
    r2r = dict((relation_tg, relation_sr)
               for relation_sr, relation_tg in relation_seeds)
    new_rules_sr = _rule_transfer(rule2conf_tg, rule2conf_sr, r2r)
    return rules_sr + new_rules_sr, rules_tg + new_rules_tg, {'sr': new_rules_sr, 'tg': new_rules_tg}


def completion_by_aligned_entities(triples_sr, triples_tg, entity_seeds, relation_seeds):
    '''
    auto graph completion with (e1, r1, e2) -> (e1', r1', e2'), in which (e1, r1, e2) is in KG but (e1', r1', e2') is not in KG'
    triples_*: [(head, tail, relation)...]
    *_seeds: [(sr_id, tg_id)...]
    '''
    if not isinstance(triples_sr, list):
        print_time_info('sssssssssssss', print_error=True)
        raise ValueError()
    if not isinstance(triples_tg, list):
        print_time_info('sssssssssssss', print_error=True)
        raise ValueError()

    def _completion_by_aligned_entities(from_triples, to_triples, e2e, r2r):
        to_triples = set(to_triples)
        new_triples = []
        for head, tail, relation in from_triples:
            if head in e2e and tail in e2e and relation in r2r:
                to_triple_candidate = (e2e[head], e2e[tail], r2r[relation])
                if to_triple_candidate not in to_triples:
                    new_triples.append(to_triple_candidate)
        return new_triples

    e2e = dict(entity_seeds)
    _check(entity_seeds, e2e, 1)
    r2r = dict(relation_seeds)
    _check(relation_seeds, r2r, 2)

    new_triples_tg = _completion_by_aligned_entities(
        triples_sr, triples_tg, e2e, r2r)

    e2e = dict([(entity_tg, entity_sr)
                for entity_sr, entity_tg in entity_seeds])
    _check(entity_seeds, e2e, 3)
    r2r = dict([(relation_tg, relation_sr)
                for relation_sr, relation_tg in relation_seeds])
    _check(relation_seeds, r2r, 4)
    new_triples_sr = _completion_by_aligned_entities(
        triples_tg, triples_sr, e2e, r2r)
    new_triple_confs_sr = {triple: 1.0 for triple in new_triples_sr}
    new_triple_confs_tg = {triple: 1.0 for triple in new_triples_tg}
    return triples_sr + new_triples_sr, triples_tg + new_triples_tg, {'sr': new_triple_confs_sr, 'tg': new_triple_confs_tg}


class CrossGraphCompletion(object):

    def __init__(self, directory, train_seeds_ratio):
        '''
        we followed the experiment setting of JAPE
        the folder under the directory JAPE/0_x contains the entity alignment dataset for train and test.
        '''
        if train_seeds_ratio not in {0.1, 0.2, 0.3, 0.4, 0.5}:
            print('----------------------------')
            print_time_info('Not a legal train seeds ratio: %f.' %
                            train_seeds_ratio)
            raise ValueError()

        language_sr, language_tg = directory.name.split('_')

        triples_sr, id2entity_sr, id2relation_sr, rules_sr = _load_languge(
            directory, language_sr)
        triples_tg, id2entity_tg, id2relation_tg, rules_tg = _load_languge(
            directory, language_tg)
        entity_seeds, relation_seeds = _load_seeds(
            directory, train_seeds_ratio)

        new_triple_confs = {}
        new_rules = {}
        triples_sr, triples_tg, bi_new_triple_confs = completion_by_aligned_entities(
            triples_sr, triples_tg, entity_seeds, relation_seeds)
        new_triple_confs['completion_by_aligned_entities'] = bi_new_triple_confs
        _print_result_log(bi_new_triple_confs, directory.name,
                          'completion_by_aligned_entities', 'triple')

        rules_sr, rules_tg, bi_new_rules = rule_transfer(
            rules_sr, rules_tg, relation_seeds)
        new_rules['rule_transfer'] = bi_new_rules
        _print_result_log(bi_new_rules, directory.name,
                          'rule_transfer', 'rule')
        # _print_new_rules(bi_new_rules, id2entity_sr, id2relation_tg)

        triples_sr, triples_tg, bi_new_triple_confs = rule_based_graph_completion(
            triples_sr, triples_tg, rules_sr, rules_tg)
        new_triple_confs['rule_based_graph_completion'] = bi_new_triple_confs
        _print_result_log(bi_new_triple_confs, directory.name,
                          'rule_based_graph_completion', 'triple')
        # _print_new_triple_confs(bi_new_triple_confs, id2entity_sr, id2entity_tg, id2relation_sr, id2relation_tg)


def main():
    from project_path import bin_dir
    train_seeds_ratio = 0.3
    directory = bin_dir / 'dbp15k'
    language_pair_dirs = list(directory.glob('*_en'))
    for local_directory in language_pair_dirs:
        CrossGraphCompletion(local_directory, train_seeds_ratio)
