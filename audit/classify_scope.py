import json
findings = json.load(open('findings_zero.json'))

SCOPE_OUT_TYPES = set()
meta_scope = {'APIGroup','APIGroupList','APIResource','APIResourceList','APIVersions','ApplyOptions','CreateOptions','DeleteOptions','Duration','FieldsV1','GetOptions','GroupVersionForDiscovery','List','ListOptions','PartialObjectMetadata','PartialObjectMetadataList','PatchOptions','RootPaths','ServerAddressByClientCIDR','Table','TableColumnDefinition','TableOptions','TableRow','TableRowCondition','UpdateOptions'}
arb1_scope = {'MutatingWebhook','ValidatingWebhook','MutatingWebhookConfiguration','MutatingWebhookConfigurationList','ValidatingWebhookConfiguration','ValidatingWebhookConfigurationList','ValidatingAdmissionPolicy','ValidatingAdmissionPolicyList','ValidatingAdmissionPolicyBinding','ValidatingAdmissionPolicyBindingList','ValidatingAdmissionPolicySpec','ValidatingAdmissionPolicyStatus','ValidatingAdmissionPolicyBindingSpec','ParamKind','ParamRef','MatchResources','MatchCondition','NamedRuleWithOperations','Rule','RuleWithOperations','ServiceReference','WebhookClientConfig','AuditAnnotation','ExpressionWarning','TypeChecking','Validation','Variable'}
nwb1_scope = {'Ingress','IngressList','IngressClass','IngressClassList','IngressSpec','IngressStatus','IngressTLS','IngressRule','IngressRuleValue','HTTPIngressPath','HTTPIngressRuleValue','IngressBackend','IngressClassSpec','IngressClassParametersReference','IngressLoadBalancerStatus','IngressLoadBalancerIngress','IngressPortStatus'}
for f in findings:
    if f['category'] != 'missing_type': continue
    gv, s = f['gv'], f['struct']
    if gv == 'meta/v1' and s in meta_scope: SCOPE_OUT_TYPES.add((gv, s))
    elif gv == 'admissionregistration/v1beta1' and s in arb1_scope: SCOPE_OUT_TYPES.add((gv, s))
    elif gv == 'networking/v1beta1' and s in nwb1_scope: SCOPE_OUT_TYPES.add((gv, s))

mt = [f for f in findings if f['category']=='missing_type']
in_scope = [f for f in mt if (f['gv'], f['struct']) not in SCOPE_OUT_TYPES]
print('missing_type total:', len(mt), '| documented scope-out:', len(mt)-len(in_scope), '| in-scope remaining:', len(in_scope))
for f in sorted(in_scope, key=lambda x: (x['gv'], x['struct'])):
    print('   ', f['gv'], '::', f['struct'])
