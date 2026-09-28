"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.handlers = void 0;
const sdk_1 = require("@linear/sdk");
function getClient(ctx) {
    const apiKey = ctx.secrets.LINEAR_API_KEY;
    if (!apiKey) {
        throw new Error("E_UNAUTHORIZED: Missing LINEAR_API_KEY in runtime execution envelope.");
    }
    return new sdk_1.LinearClient({ apiKey });
}
exports.handlers = {
    // 1. Create Issue
    create_issue: {
        async preview(params) {
            return {
                summary: `Create issue "${params.title}" under team ${params.teamId} with priority P${params.priority ?? 0}`,
                diff: { targetTeam: params.teamId, title: params.title, priority: params.priority ?? 0 },
                reversible: true
            };
        },
        async execute(params, ctx) {
            const client = getClient(ctx);
            const issuePayload = await client.createIssue({
                teamId: params.teamId,
                title: params.title,
                description: params.description,
                priority: params.priority ?? 0
            });
            const issue = await issuePayload.issue;
            return {
                receiptId: `rc_lin_${issue?.id}_${Date.now()}`,
                status: "COMPLETED",
                resource: { id: issue?.id, identifier: issue?.identifier, url: issue?.url }
            };
        }
    },
    // 2. Update Priority
    update_priority: {
        async preview(params) {
            return {
                summary: `Update priority for issue ${params.issueId} to P${params.priority}`,
                diff: { issueId: params.issueId, newPriority: params.priority },
                reversible: true
            };
        },
        async execute(params, ctx) {
            const client = getClient(ctx);
            const result = await client.updateIssue(params.issueId, { priority: params.priority });
            const issue = await result.issue;
            return {
                receiptId: `rc_lin_pri_${params.issueId}_${Date.now()}`,
                status: "COMPLETED",
                resource: { id: issue?.id, identifier: issue?.identifier, priority: issue?.priority }
            };
        }
    },
    // 3. Assign User
    assign_user: {
        async preview(params) {
            return {
                summary: `Reassign issue ${params.issueId} to user ${params.assigneeId}`,
                diff: { issueId: params.issueId, newAssignee: params.assigneeId },
                reversible: true
            };
        },
        async execute(params, ctx) {
            const client = getClient(ctx);
            const result = await client.updateIssue(params.issueId, { assigneeId: params.assigneeId });
            const issue = await result.issue;
            return {
                receiptId: `rc_lin_assign_${params.issueId}_${Date.now()}`,
                status: "COMPLETED",
                resource: { id: issue?.id, assigneeId: params.assigneeId }
            };
        }
    },
    // 4. Add Comment
    add_comment: {
        async preview(params) {
            return {
                summary: `Post audit comment to issue ${params.issueId}`,
                diff: { issueId: params.issueId, bodySnippet: params.body.slice(0, 80) + "..." },
                reversible: false
            };
        },
        async execute(params, ctx) {
            const client = getClient(ctx);
            const commentPayload = await client.createComment({
                issueId: params.issueId,
                body: params.body
            });
            const comment = await commentPayload.comment;
            return {
                receiptId: `rc_lin_cmt_${comment?.id}`,
                status: "COMPLETED",
                resource: { id: comment?.id, issueId: params.issueId }
            };
        }
    },
    // 5. Transition Status
    transition_status: {
        async preview(params) {
            return {
                summary: `Transition state of issue ${params.issueId} to state ID ${params.stateId}`,
                diff: { issueId: params.issueId, targetStateId: params.stateId },
                reversible: true
            };
        },
        async execute(params, ctx) {
            const client = getClient(ctx);
            const result = await client.updateIssue(params.issueId, { stateId: params.stateId });
            const issue = await result.issue;
            return {
                receiptId: `rc_lin_trans_${params.issueId}_${Date.now()}`,
                status: "COMPLETED",
                resource: { id: issue?.id, stateId: params.stateId }
            };
        }
    },
    // 6. Close Sprint Issue
    close_sprint_issue: {
        async preview(params) {
            return {
                summary: `Close issue ${params.issueId} and finalize resolution`,
                diff: { issueId: params.issueId, resolutionNote: params.resolutionNote ?? "None" },
                reversible: true
            };
        },
        async execute(params, ctx) {
            const client = getClient(ctx);
            const issue = await client.issue(params.issueId);
            const team = await issue.team;
            const states = await team?.states();
            const doneState = states?.nodes.find((s) => s.type === "completed");
            if (!doneState) {
                throw new Error("E_STATE_NOT_FOUND: Could not resolve a completed workflow state.");
            }
            if (params.resolutionNote) {
                await client.createComment({
                    issueId: params.issueId,
                    body: `**Resolution Summary:** ${params.resolutionNote}`
                });
            }
            await client.updateIssue(params.issueId, { stateId: doneState.id });
            return {
                receiptId: `rc_lin_close_${params.issueId}_${Date.now()}`,
                status: "COMPLETED",
                resource: { id: params.issueId, finalState: doneState.name }
            };
        }
    },
    // 7. Attach Signed Log
    attach_signed_log: {
        async preview(params) {
            return {
                summary: `Attach signed audit trail "${params.title}" to issue ${params.issueId}`,
                diff: { issueId: params.issueId, title: params.title, byteSize: Buffer.byteLength(params.logData) },
                reversible: false
            };
        },
        async execute(params, ctx) {
            const client = getClient(ctx);
            const formattedLog = `### 🔒 RailCall Audit Receipt: ${params.title}\n\`\`\`json\n${params.logData}\n\`\`\``;
            const commentPayload = await client.createComment({
                issueId: params.issueId,
                body: formattedLog
            });
            const comment = await commentPayload.comment;
            return {
                receiptId: `rc_lin_audit_${comment?.id}`,
                status: "COMPLETED",
                resource: { id: comment?.id, issueId: params.issueId }
            };
        }
    }
};
